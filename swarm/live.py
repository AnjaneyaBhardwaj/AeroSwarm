"""Live mode for the run viewer (local only): start a real swarm run from the dial values and stream it.

    uv run python -m swarm.live            # http://127.0.0.1:8000 serves viewer/ and the API below
    make live

The server adds no optimization logic. A run is `swarm.run.run` on the hard preset with the dial values as the
start design, in a background thread, writing `runs/live/<id>/` like any other run. The stream re-reads that
directory with `swarm.viz.export.export_run`, so the records it sends are the same ones a recorded replay uses.
A generation is sent once the next one has started (or the run has ended), so it is never sent half-written.
When the run ends it is exported, with its Optuna comparison, to `viewer/runs/live/<name>.json` and shows up in
the gallery (merged into `/runs/index.json`; the committed index is not touched).

API:
  GET  /api/health                  LLM availability, defaults, caps, per-model cost estimate
  POST /api/check                   {start} -> the geometry and rulebook violations a run would refuse
  POST /api/runs                    {start, max_evals, budget_usd, llm, model, inner_optimizer} -> {run_id}
  POST /api/runs/{id}/stop          end the run at the next step boundary (termination "stopped")
  GET  /api/runs/{id}/stream        Server-Sent Events: run, generation, progress (with what is happening now),
                                    done | error
  GET  /runs/index.json             committed gallery + finished live runs

Every live run is capped: at most MAX_EVALS evaluations and MAX_BUDGET_USD estimated LLM spend (the run stops
cleanly with termination `cost_cap`), 30 minutes wall clock, and one run at a time. Only whoever started a run
can stop it (the start response carries a control token).

Deploying on a public site (docs/DEPLOY.md), configured by environment variables:
  AEROSWARM_LIVE_ACCESS_CODE   required in the request to start a real-LLM run (mock runs stay open)
  AEROSWARM_LIVE_DAILY_USD     estimated real-LLM spend allowed per UTC day across all runs (default 10)
  AEROSWARM_LIVE_ORIGINS       comma-separated origins allowed to call the API (a frontend on another domain)
The server refuses to bind a non-local address without an access code unless --allow-open is given.
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import secrets
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from swarm.cad.build import build
from swarm.llm.client import PRICES, AnthropicClient, MissingAPIKey, TraceLogger, require_api_key
from swarm.llm.mock import MockClient
from swarm.run import HARD_SPEC, HARD_START, run
from swarm.solvers.xfoil import xfoil_available
from swarm.state import SINGLE_ELEMENT_PARAMS, WingParams
from swarm.viz.export import export_run, index_entries, make_index, optuna_baseline

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_EVALS = 15
DEFAULT_BUDGET_USD = 1.0
MAX_EVALS = 40
MAX_BUDGET_USD = 5.0
MAX_WALL_HOURS = 0.5
DEFAULT_DAILY_USD = 10.0
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
# Tokens per evaluation in the committed example run (264,277 in / 94,058 out over 23 evaluations, LLM-only).
# Hybrid runs use fewer calls per evaluation, so this is an upper-side estimate.
TOKENS_PER_EVAL = (11_490, 4_090)


def cost_per_eval(model: str) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    return (TOKENS_PER_EVAL[0] * p[0] + TOKENS_PER_EVAL[1] * p[1]) / 1e6


class StartRequest(BaseModel):
    start: dict[str, float]
    max_evals: int = Field(DEFAULT_EVALS, ge=1, le=MAX_EVALS)
    budget_usd: float = Field(DEFAULT_BUDGET_USD, gt=0, le=MAX_BUDGET_USD)
    llm: Literal["anthropic", "mock"] = "anthropic"
    model: str = DEFAULT_MODEL
    inner_optimizer: bool = True
    access_code: str = ""


class StopRequest(BaseModel):
    token: str = ""


class DailySpend:
    """Estimated real-LLM spend per UTC day, kept in a JSON file so a restart does not reset the daily cap.
    A run reserves its full per-run cap when it starts; the reservation becomes the actual spend when it ends."""

    def __init__(self, path: Path, cap_usd: float):
        self.path, self.cap = path, cap_usd
        self._lock = threading.Lock()

    @staticmethod
    def _day() -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, book: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(book))

    def spent(self) -> float:
        return float(self._load().get(self._day(), 0.0))

    def reserve(self, usd: float) -> bool:
        with self._lock:
            book, day = self._load(), self._day()
            if book.get(day, 0.0) + usd > self.cap + 1e-9:
                return False
            book[day] = round(book.get(day, 0.0) + usd, 6)
            self._save(book)
            return True

    def settle(self, reserved: float, actual: float) -> None:
        with self._lock:
            book, day = self._load(), self._day()
            book[day] = round(max(0.0, book.get(day, 0.0) - reserved + actual), 6)
            self._save(book)


class LiveRun:
    def __init__(self, run_id: str, run_dir: Path, req: StartRequest):
        self.id = run_id
        self.dir = run_dir
        self.req = req
        self.trace = TraceLogger(run_dir / "traces.jsonl")
        self.started = time.time()
        self.thread: threading.Thread | None = None
        self.finished = threading.Event()
        self.error: str | None = None
        self.final: dict | None = None  # the full export, with the Optuna comparison, once the run has ended
        self.token = secrets.token_urlsafe(16)  # lets whoever started the run stop it


def _client(req: StartRequest, trace: TraceLogger):
    if req.llm == "mock":
        return MockClient(trace, inject_faults=False)
    return AnthropicClient(trace, model=req.model)


def create_app(
    viewer_dir: str | Path = "viewer",
    runs_root: str | Path = "runs/live",
    baselines_root: str | Path = "runs/viewer_baselines",
    poll_s: float = 1.0,
    baseline: bool = True,
    access_code: str | None = None,
    daily_usd: float = DEFAULT_DAILY_USD,
    cors_origins: list[str] | tuple[str, ...] = (),
) -> FastAPI:
    """`access_code`: required to start a real-LLM run (None: no code, for local use). `daily_usd`: estimated
    real-LLM spend allowed per UTC day. `cors_origins`: other origins whose pages may call this API."""
    viewer_dir, runs_root, baselines_root = Path(viewer_dir), Path(runs_root), Path(baselines_root)
    live_out = viewer_dir / "runs" / "live"
    spend = DailySpend(runs_root / "_daily_spend.json", daily_usd)
    app = FastAPI(title="AeroSwarm live")
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )
    runs: dict[str, LiveRun] = {}
    lock = threading.Lock()

    def has_key() -> bool:
        try:
            require_api_key()
            return True
        except MissingAPIKey:
            return False

    def busy() -> LiveRun | None:
        return next((r for r in runs.values() if not r.finished.is_set()), None)

    @app.get("/api/health")
    def health() -> dict:
        cur = busy()
        return {
            "ok": True,
            "anthropic_key": has_key(),
            "access_code_required": bool(access_code),
            "xfoil": xfoil_available(),  # without it designs cannot be verified, so no run can pass
            "daily": {"cap_usd": spend.cap, "spent_usd": round(spend.spent(), 2)},
            "busy": cur.id if cur else None,
            "spec": {"target_cl": HARD_SPEC.target_cl, "cl_tol": HARD_SPEC.cl_tol, "cd_max": HARD_SPEC.cd_max},
            "defaults": {
                "model": DEFAULT_MODEL,
                "max_evals": DEFAULT_EVALS,
                "budget_usd": DEFAULT_BUDGET_USD,
                "inner_optimizer": True,
            },
            "caps": {"max_evals": MAX_EVALS, "budget_usd": MAX_BUDGET_USD, "wall_minutes": MAX_WALL_HOURS * 60},
            "models": {m: cost_per_eval(m) for m in PRICES},
            "bounds": {k: v for k, v in WingParams.bounds().items() if k in SINGLE_ELEMENT_PARAMS},
            "default_start": {k: getattr(HARD_START, k) for k in SINGLE_ELEMENT_PARAMS},
        }

    def parse_start(values: dict[str, float]) -> WingParams:
        unknown = set(values) - set(SINGLE_ELEMENT_PARAMS)
        if unknown:
            raise HTTPException(400, f"unknown parameters: {sorted(unknown)}")
        try:
            return WingParams(**values)
        except ValidationError as e:
            raise HTTPException(400, f"start design out of bounds: {e.errors()[0]['msg']}") from e

    def violations(start: WingParams) -> list[str]:
        """The run's own geometry and rulebook checks (cad.build), so the page can say before a run starts."""
        return build(start, HARD_SPEC, runs_root / "_checks" / start.cid).violations

    @app.post("/api/check")
    def check(body: dict[str, dict[str, float]]) -> dict:
        start = parse_start(body.get("start", {}))
        v = violations(start)
        return {"ok": not v, "violations": v, "rulebook": HARD_SPEC.rulebook}

    @app.post("/api/runs")
    def start_run(req: StartRequest) -> dict:
        start = parse_start(req.start)
        spec = HARD_SPEC.model_copy(
            update={"max_evals": req.max_evals, "max_cost_usd": req.budget_usd, "max_wall_hours": MAX_WALL_HOURS}
        )
        if req.llm == "anthropic":
            if req.model not in PRICES:
                raise HTTPException(400, f"unknown model {req.model!r}; choose one of {sorted(PRICES)}")
            if not has_key():
                raise HTTPException(400, "no Anthropic API key: set AEROSWARM_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY")
            if access_code and not hmac.compare_digest(req.access_code.encode(), access_code.encode()):
                raise HTTPException(403, "a real-LLM run needs the access code (the mock is open to everyone)")
        reserved = req.budget_usd if req.llm == "anthropic" else 0.0
        with lock:
            cur = busy()
            if cur is not None:
                raise HTTPException(409, f"run {cur.id} is still going; one live run at a time")
            run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
            v = violations(start)
            if v:
                raise HTTPException(400, "start design fails the geometry/rule checks: " + "; ".join(v))
            if reserved and not spend.reserve(reserved):
                left = max(0.0, spend.cap - spend.spent())
                raise HTTPException(
                    429, f"today's live-run budget is used up (${left:.2f} of ${spend.cap:.2f} left); try the mock"
                )
            lr = LiveRun(run_id, runs_root / run_id, req)
            runs[run_id] = lr

        def work() -> None:
            name = f"live_{run_id}"
            try:
                run(
                    spec,
                    start,
                    run_id=run_id,
                    runs_root=runs_root,
                    llm=_client(req, lr.trace),
                    preset="hard",
                    inner_optimizer=req.inner_optimizer,
                )
                base = optuna_baseline(lr.dir, baselines_root / f"{name}_optuna") if baseline else None
                lr.final = export_run(lr.dir, name=name, baseline=base)
                live_out.mkdir(parents=True, exist_ok=True)
                (live_out / f"{name}.json").write_text(json.dumps(lr.final, separators=(",", ":")))
            except Exception as e:  # reported to the page; the run directory keeps whatever was written
                lr.error = f"{type(e).__name__}: {e}"[:500]
            finally:
                if reserved:
                    spend.settle(reserved, lr.trace.totals["cost_usd"])
                lr.finished.set()

        lr.thread = threading.Thread(target=work, name=f"live-{run_id}", daemon=True)
        lr.thread.start()
        return {"run_id": run_id, "estimate_usd": _estimate(req), "control_token": lr.token}

    @app.post("/api/runs/{run_id}/stop")
    def stop_run(run_id: str, body: StopRequest) -> dict:
        lr = runs.get(run_id)
        if lr is None:
            raise HTTPException(404, f"no live run {run_id}")
        if not hmac.compare_digest(body.token.encode(), lr.token.encode()):
            raise HTTPException(403, "only whoever started this run can stop it")
        if not lr.finished.is_set():
            lr.trace.request_stop()
        return {"run_id": run_id, "stopping": not lr.finished.is_set()}

    @app.get("/api/runs/{run_id}/stream")
    async def stream(run_id: str) -> StreamingResponse:
        lr = runs.get(run_id)
        if lr is None:
            raise HTTPException(404, f"no live run {run_id}")
        # X-Accel-Buffering: nginx and similar proxies must pass events through as they come
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(_events(lr, poll_s), media_type="text/event-stream", headers=headers)

    @app.get("/runs/index.json")
    def index() -> JSONResponse:
        base = viewer_dir / "runs" / "index.json"
        entries = json.loads(base.read_text())["runs"] if base.exists() else []
        if live_out.exists():
            entries += index_entries(live_out, prefix="live/")
        return JSONResponse(make_index(entries), headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=viewer_dir, html=True), name="viewer")
    return app


def _estimate(req: StartRequest) -> float | None:
    if req.llm == "mock":
        return 0.0
    per = cost_per_eval(req.model)
    return None if per is None else round(min(req.budget_usd, per * req.max_evals), 2)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


# What the run is doing now, from the node of its newest event (the graph writes a node's events when it returns).
NEXT_STEP = {
    "chief_plan": "The CAD agent is choosing the change",
    "cad_propose": "Building the geometry and checking the rules",
    "geometry_build": "The solver is running",
    "cfd_solve": "Checking the solver result",
    "cfd_recover": "The solver is retrying with safer settings",
    "numeric_validate": "The Critic is reviewing the result",
    "inner_optimize": "Optuna is searching (no LLM)",
}


def _phase(lr: LiveRun) -> dict:
    """{"gen", "phase"}: the generation in progress and a plain description of its current step."""
    if lr.trace.stop_requested and not lr.finished.is_set():
        return {"gen": None, "phase": "Stopping after the current step"}
    last = None
    try:
        lines = (lr.dir / "events.jsonl").read_text().splitlines()
        last = json.loads(lines[-1]) if lines else None
    except (OSError, ValueError):
        pass
    if last is None:
        return {"gen": 0, "phase": "The Chief is planning the first step"}
    gen, node = last.get("gen", 0), last.get("node")
    if node == "critic":
        return {"gen": gen + 1, "phase": "The Chief is planning the next step"}
    if node == "report":
        return {"gen": gen, "phase": "Writing the report and the Optuna comparison"}
    return {"gen": gen, "phase": NEXT_STEP.get(node, "Working")}


def _snapshot(lr: LiveRun) -> dict | None:
    """The run as exported so far; None while meta.json is not written yet or a file is mid-write."""
    if not (lr.dir / "meta.json").exists():
        return None
    try:
        return export_run(lr.dir, name=f"live_{lr.id}")
    except (ValueError, KeyError, ValidationError):  # a JSONL line caught mid-write: next tick
        return None


async def _events(lr: LiveRun, poll_s: float):
    """run (header, once) -> generation (each complete one, in order) / progress ... -> done | error."""
    sent_header, sent = False, 0
    while True:
        finished = lr.finished.is_set()
        snap = lr.final if (finished and lr.final) else await asyncio.to_thread(_snapshot, lr)
        if snap is not None:
            if not sent_header:
                head = {k: v for k, v in snap.items() if k not in ("generations", "outlines")}
                head["outlines"] = {snap["start_cid"]: snap["outlines"][snap["start_cid"]]}
                head["estimate_usd"] = _estimate(lr.req)
                head["budget_usd"] = lr.req.budget_usd
                yield _sse("run", head)
                sent_header = True
            # a generation is complete once a later one has started (any trace, event or record of it)
            last = max((g["gen"] for g in snap["generations"]), default=-1)
            ready = [g for g in snap["generations"] if g["head"] >= 0 and (finished or g["gen"] < last)]
            for g in ready[sent:]:
                cids = {e["cid"] for e in g["evals"]}
                yield _sse("generation", {"generation": g, "outlines": {c: snap["outlines"][c] for c in cids}})
            sent = max(sent, len(ready))
            t = lr.trace.totals
            yield _sse(
                "progress",
                {
                    "evals": snap["evals"],
                    "cost_usd": round(t["cost_usd"], 4),
                    "llm_calls": t["calls"],
                    "elapsed_s": round(time.time() - lr.started, 1),
                    "finished": finished,
                    **_phase(lr),
                },
            )
        if finished:
            if lr.error:
                yield _sse("error", {"message": lr.error})
            elif lr.final:
                yield _sse("done", lr.final)
            return
        await asyncio.sleep(poll_s)


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: this machine only)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--allow-open", action="store_true", help="bind a public address without an access code")
    ap.add_argument("--proxy-headers", action="store_true", help="trust X-Forwarded-* from a reverse proxy")
    a = ap.parse_args(argv)
    code = os.environ.get("AEROSWARM_LIVE_ACCESS_CODE") or None
    if a.host not in LOCAL_HOSTS and not code and not a.allow_open:
        sys.exit(
            f"refusing to listen on {a.host} without AEROSWARM_LIVE_ACCESS_CODE: anyone who finds the page could "
            "spend your API credit. Set the access code (or pass --allow-open to accept that)."
        )
    origins = [o.strip() for o in os.environ.get("AEROSWARM_LIVE_ORIGINS", "").split(",") if o.strip()]
    app = create_app(
        access_code=code,
        daily_usd=float(os.environ.get("AEROSWARM_LIVE_DAILY_USD", DEFAULT_DAILY_USD)),
        cors_origins=origins,
    )
    uvicorn.run(app, host=a.host, port=a.port, log_level="info", proxy_headers=a.proxy_headers)


if __name__ == "__main__":
    main()
