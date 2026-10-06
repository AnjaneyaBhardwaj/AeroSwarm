"""CLI: run an optimization.

python -m swarm.run                      # demo spec; real LLM if an Anthropic key env var is set (see llm/client.py)
python -m swarm.run --llm mock           # force the labelled mock (not an LLM)
python -m swarm.run --preset hard        # 85% of attached Cl,max: TE separation + stall-margin rejections
python -m swarm.run --max-evals 10 --budget-usd 2.00   # live-run caps
python -m swarm.run --llm anthropic ...  # needs ANTHROPIC_API_KEY (startup error without); exit 3 = INVALID run
python -m swarm.run --resume <run_id>    # resume from runs/<run_id>/ckpt.db
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from swarm.graph import build_graph, checkpointer
from swarm.ledger import RunFiles
from swarm.llm.client import LLMClient, MissingAPIKey, TraceLogger, make_client, preflight_llm
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
# Rulebook: FSAE 2027 (DesignSpec default). T.7.1.4's 5 mm leading-edge radius needs t >= 0.123 on the
# 300 mm chord, so both starts use t 0.13 (they were 0.12 and 0.10 under Formula Student 2026).
DEMO_START = WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.13, alpha_deg=4.0)

# "Hard" preset: a near-stall target at a low-speed-corner Re (3e5 ≈ 15 m/s on the
# 300 mm chord), derived from the GATED XFoil sweep (scripts/gated_sweep.py; docs/PROGRESS.md,
# sessions 7, 8 and 12): a design counts only if it is attached at alpha, alpha+1 and alpha+2 and
# keeps d|Cl|/dalpha >= 0.05/deg there (the pipeline's full gate).
# Under FSAE 2027 (thickness >= 0.123, sweep levels 0.125-0.15): gated Cl_max 1.985; the
# -1.83 ± 0.03, Cd <= 0.025 box holds 42 passing grid points, 18 off the bounds (camber < 0.09,
# thickness > 0.125), and all 42 pass cold through the pipeline. (The strict "hardest box with
# >= 10 interior points" rule would give -1.84 with 13.) Under Formula Student 2026 the same box
# held 28 points, 13 interior. XFoil-derived: re-check when the OpenFOAM tiers arrive.
HARD_SPEC = DesignSpec(
    component="wing_1el",
    target_cl=-1.83,
    cl_tol=0.03,
    cd_max=0.025,
    speed_mps=round(speed_for_reynolds(3.0e5, PLACEHOLDER_CAR.chord_mm), 2),
    max_evals=30,
    max_wall_hours=0.5,
)
HARD_START = WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.13, alpha_deg=8.0)

PRESETS: dict[str, tuple[DesignSpec, WingParams]] = {
    "default": (DEMO_SPEC, DEMO_START),
    "hard": (HARD_SPEC, HARD_START),
}


def run(
    spec: DesignSpec,
    start: WingParams,
    run_id: str | None = None,
    runs_root: str | Path = "runs",
    llm: LLMClient | None = None,
    which: str = "auto",
    inject_faults: bool = False,
    resume: bool = False,
    preset: str | None = None,
    start_seed: int | None = None,
) -> dict:
    if llm is None:
        preflight_llm(which)  # MissingAPIKey before any run directory exists
    run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    files = RunFiles(Path(runs_root) / run_id)
    if llm is None:
        llm = make_client(TraceLogger(files.traces), which, inject_faults=inject_faults)
    if not llm.is_mock and spec.max_cost_usd is None and not resume:
        print("warning: real LLM run without a cost cap; pass --budget-usd to bound spend", file=sys.stderr)
    meta = (
        {}
        if resume
        else {
            "run_id": run_id,
            "preset": preset,
            "spec": spec.model_dump(),
            "start": start.model_dump(),
            "start_seed": start_seed,  # set when the start was sampled by baselines.random_start
        }
    )
    files.write_meta(
        {
            **meta,
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
                "history": [],
                "exploration": None,
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
    ap.add_argument("--preset", choices=sorted(PRESETS), default="default")
    ap.add_argument("--max-evals", type=int, help="evaluation budget (default: the preset's)")
    ap.add_argument(
        "--budget-usd",
        type=float,
        help="stop cleanly once the estimated LLM cost reaches this (USD); calls with unknown pricing count as over",
    )
    ap.add_argument("--max-wall-hours", type=float, help="wall-clock limit in hours (default: the preset's)")
    ap.add_argument("--start-seed", type=int, help="start from a seeded random feasible design (recorded in meta.json)")
    ap.add_argument("--resume", metavar="RUN_ID")
    ap.add_argument("--no-faults", action="store_true", help="mock: skip the injected demo fault")
    a = ap.parse_args(argv)
    if a.max_evals is not None and a.max_evals < 1:
        ap.error("--max-evals must be >= 1")
    if a.budget_usd is not None and a.budget_usd <= 0:
        ap.error("--budget-usd must be > 0")
    spec, start = PRESETS[a.preset]
    upd: dict = {}
    if a.max_evals is not None:
        upd["max_evals"] = a.max_evals
    if a.budget_usd is not None:
        upd["max_cost_usd"] = a.budget_usd
    if a.max_wall_hours is not None:
        upd["max_wall_hours"] = a.max_wall_hours
    if a.resume and (upd or a.preset != "default" or a.start_seed is not None):
        ap.error("--resume continues the checkpointed spec; --preset/--max-evals/--budget-usd are fixed at run start")
    spec = spec.model_copy(update=upd)
    if a.start_seed is not None:
        from swarm.baselines import random_start

        start = random_start(a.start_seed, spec)
    try:
        preflight_llm(a.llm)
    except MissingAPIKey as e:
        ap.error(str(e))
    final = run(
        spec,
        start,
        run_id=a.resume or a.run_id,
        runs_root=a.runs_root,
        which=a.llm,
        inject_faults=not a.no_faults,
        resume=bool(a.resume),
        preset=None if a.resume else a.preset,
        start_seed=a.start_seed,
    )
    meta = json.loads((Path(final["run_dir"]) / "meta.json").read_text())
    health = meta.get("llm_health") or {}
    print(
        json.dumps(
            {
                **{
                    k: meta.get(k)
                    for k in (
                        "run_id",
                        "preset",
                        "llm_client",
                        "termination",
                        "evals",
                        "best_passing_cid",
                        "closest_candidate_cid",
                        "closest_candidate_failing",
                        "viz",
                    )
                },
                "llm_valid": health.get("valid"),
            },
            indent=1,
        )
    )
    print(f"report: {final['run_dir']}/report.md")
    if health.get("enforced") and not health.get("valid"):
        print("INVALID RUN: " + "; ".join(health["invalid_reasons"]), file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
