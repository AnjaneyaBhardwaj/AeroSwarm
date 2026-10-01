"""CLI: run an optimization.

python -m swarm.run                      # demo spec; real LLM if ANTHROPIC_API_KEY is set
python -m swarm.run --llm mock           # force the labelled mock (not an LLM)
python -m swarm.run --resume <run_id>    # resume from runs/<run_id>/ckpt.db
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

from swarm.graph import build_graph, checkpointer
from swarm.ledger import RunFiles
from swarm.llm.client import LLMClient, TraceLogger, make_client
from swarm.solvers.xfoil import xfoil_available
from swarm.state import PLACEHOLDER_CAR, DesignSpec, WingParams, speed_for_reynolds

# BLUEPRINT §4 build path v0. Speed chosen so Re ≈ 8.3e5 on the 300 mm chord.
DEMO_SPEED = round(speed_for_reynolds(8.3e5, PLACEHOLDER_CAR.chord_mm), 2)
DEMO_SPEC = DesignSpec(
    component="wing_1el",
    target_cl=-1.50,
    cl_tol=0.03,
    cd_max=0.018,
    speed_mps=DEMO_SPEED,
    max_evals=30,
    max_wall_hours=0.5,
)
DEMO_START = WingParams(main_camber=0.02, main_camber_pos=0.40, main_thickness=0.12, alpha_deg=4.0)


def run(
    spec: DesignSpec,
    start: WingParams,
    run_id: str | None = None,
    runs_root: str | Path = "runs",
    llm: LLMClient | None = None,
    which: str = "auto",
    inject_faults: bool = False,
    resume: bool = False,
) -> dict:
    run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    files = RunFiles(Path(runs_root) / run_id)
    if llm is None:
        llm = make_client(TraceLogger(files.traces), which, inject_faults=inject_faults)
    files.write_meta(
        {
            "run_id": run_id,
            "spec": spec.model_dump(),
            "start": start.model_dump(),
            "llm_client": llm.label,
            "llm_kind": llm.kind,
            "is_mock": llm.is_mock,
            "mock_notice": "MockClient is a deterministic rule-based stand-in for tests/demos, NOT an LLM; "
            "never use mock runs as the LLM arm of a comparison."
            if llm.is_mock
            else None,
            "xfoil_available": xfoil_available(),
        }
    )
    graph = build_graph(llm, files, start)
    # explicit cap; LangGraph 1.x defaults to 10007 [BLUEPRINT S10]
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 1000}
    with checkpointer(files.dir / "ckpt.db") as cp:
        app = graph.compile(checkpointer=cp)
        init = (
            None
            if resume
            else {
                "spec": spec,
                "run_dir": str(files.dir),
                "generation": 0,
                "strategy": None,
                "params": start,
                "parent": None,
                "delta": None,
                "geometry": None,
                "result": None,
                "verdict": None,
                "ledger": [],
                "events": [],
                "retries": {},
                "pending_violation": None,
                "termination": None,
                "started_at": time.time(),
            }
        )
        final = app.invoke(init, config=config)
    final["run_dir"] = str(files.dir)
    return final


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", choices=["auto", "anthropic", "mock"], default="auto")
    ap.add_argument("--run-id")
    ap.add_argument("--runs-root", default="runs")
    ap.add_argument("--max-evals", type=int, default=DEMO_SPEC.max_evals)
    ap.add_argument("--resume", metavar="RUN_ID")
    ap.add_argument("--no-faults", action="store_true", help="mock: skip the injected demo fault")
    a = ap.parse_args(argv)
    spec = DEMO_SPEC.model_copy(update={"max_evals": a.max_evals})
    final = run(
        spec,
        DEMO_START,
        run_id=a.resume or a.run_id,
        runs_root=a.runs_root,
        which=a.llm,
        inject_faults=not a.no_faults,
        resume=bool(a.resume),
    )
    meta = json.loads((Path(final["run_dir"]) / "meta.json").read_text())
    print(
        json.dumps(
            {
                k: meta.get(k)
                for k in ("run_id", "llm_client", "termination", "evals", "best_cid", "best_xfoil_cid", "viz")
            },
            indent=1,
        )
    )
    print(f"report: {final['run_dir']}/report.md")


if __name__ == "__main__":
    main()
