"""OpenFOAM recovery-ladder evaluation (milestone 5 part 2): failing setups, recovered or not, per policy.

    uv run python scripts/of_recovery.py run --policy deterministic --parallel 3   # needs OpenFOAM
    uv run python scripts/of_recovery.py run --policy llm --parallel 3             # + AEROSWARM_ANTHROPIC_API_KEY
    uv run python scripts/of_recovery.py report                                    # docs/OPENFOAM_RECOVERY.md

Each case is a design with an L0 setup that fails (found in part 1, or injected); the ladder then runs as in a
graph run (`solver.evaluate_with_recovery`): the policy picks a level after each failure, code forbids repeats.
Policies: deterministic (the failure-class preference, `recovery.default_level`) and llm (the CFD agent,
`agents.cfd.choose`, with the real client; its calls are traced to evals/of_recovery_traces.jsonl, not
committed). Work files: runs/of_recovery/<policy>/.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from swarm.agents import cfd
from swarm.cad.build import main_section, naca4
from swarm.run import HARD_SPEC
from swarm.solvers.openfoam import exec as foam
from swarm.solvers.openfoam.case import SolverOverrides
from swarm.solvers.openfoam.recovery import classify
from swarm.solvers.openfoam.solver import DEFAULT_MESH, evaluate_with_recovery
from swarm.state import WingParams, speed_for_reynolds

RE6E6 = HARD_SPEC.model_copy(update={"speed_mps": speed_for_reynolds(6e6, HARD_SPEC.car.chord_mm), "rulebook": "none"})
WITNESS = WingParams(main_camber=0.085, main_camber_pos=0.35, main_thickness=0.135, alpha_deg=8.75)
NACA0012 = WingParams(main_camber=0.0, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=10.0)
# The default setup (part 1: first-order k/omega, PCG) converged where part 1's crashes happened (first cell 5e-6
# and 2e-6 c, far field 300 and 500 c, the witness at alpha 14): the failing setups below are what remains.
CASES = {
    "early_blowup": ("witness design, relaxation U 0.9 / p 0.5 / turbulence 0.9 (blows up within 50 iterations)",
                     WITNESS, "hard", {"relax_U": 0.9, "relax_p": 0.5, "relax_turb": 0.9}, {}),
    "late_divergence": ("witness design, relaxation U 0.9 (residuals grow after iteration 50)",
                        WITNESS, "hard", {"relax_U": 0.9}, {}),
    "coarse_surface": ("NACA 0012 Re 6e6 alpha 10, 160 cells around (diverged in the mesh study)",
                       NACA0012, "re6e6", {}, {"n_surface": 160}),
    "fast_growth": ("NACA 0012 Re 6e6 alpha 10, wall-normal growth 1.16 (diverged in the mesh study)",
                    NACA0012, "re6e6", {}, {"growth": 1.16}),
    "bad_mesh": ("m 0.09 at 0.2 c, t 0.08, alpha 5: the O-grid fails checkMesh (90 deg non-orthogonality)",
                 WingParams(main_camber=0.09, main_camber_pos=0.2, main_thickness=0.08, alpha_deg=5.0), "hard", {}, {}),
}  # fmt: skip
ROOT = Path("runs/of_recovery")
DOC = Path("docs/OPENFOAM_RECOVERY.md")


def cache(policy: str) -> Path:
    return Path(f"evals/openfoam_recovery_{policy}.json")


def chooser(policy: str):
    if policy == "deterministic":
        return lambda failure, tried: cfd.fallback(failure, tried)
    from swarm.llm.client import AnthropicClient, TraceLogger

    llm = AnthropicClient(TraceLogger(Path("evals/of_recovery_traces.jsonl")))

    def pick(failure, tried):
        action, _note = cfd.choose(llm, spec_for(failure["case"]), failure, tried)
        return action

    return pick


def spec_for(case: str):
    return RE6E6 if CASES[case][2] == "re6e6" else HARD_SPEC.model_copy(update={"rulebook": "none"})


def one(job: tuple[str, str]) -> dict:
    name, policy = job
    text, params, _, ov, mesh_upd = CASES[name]
    spec = spec_for(name)
    coords = naca4(0.0, 0.4, 0.12, n=201, te_thick=0.002) if params == NACA0012 else main_section(params)
    mesh = dataclasses.replace(DEFAULT_MESH, **mesh_upd)
    pick = chooser(policy)
    t0 = time.time()

    def choose(failure, tried):
        return pick({**failure, "case": name}, tried)

    try:
        r, attempts = evaluate_with_recovery(
            params, spec, ROOT / policy / name, choose, SolverOverrides(**ov), mesh, coords=coords
        )
    except Exception as e:
        print(f"{policy} {name}: error {e!r}", flush=True)
        return {"case": name, "policy": policy, "error": repr(e)[:300]}
    first = attempts[0]
    row = {
        "case": name,
        "policy": policy,
        "description": text,
        "l0_failed": first["status"] != "converged",
        "l0_signature": first.get("signature"),
        "l0_class": classify(first.get("signature"), first["status"]),
        "recovered": first["status"] != "converged" and r.status == "converged",
        "final_status": r.status,
        "final_level": attempts[-1]["level"],
        "cl": r.cl,
        "cd": r.cd,
        "attempts": attempts,
        "wall_s": round(time.time() - t0, 1),
    }
    print(f"{policy} {name}: L0 {first['status']} -> {r.status} via {[a['level'] for a in attempts]}", flush=True)
    return row


def cmd_run(policy: str, parallel: int, cases: list[str]) -> None:
    if not foam.available():
        sys.exit("OpenFOAM not found")
    with Pool(parallel) as pool:
        rows = pool.map(one, [(c, policy) for c in cases])
    if cache(policy).exists():  # keep the other cases' rows; replace the ones re-run
        old = [r for r in json.loads(cache(policy).read_text())["rows"] if r["case"] not in cases]
        rows = sorted(old + rows, key=lambda r: list(CASES).index(r["case"]) if r["case"] in CASES else 99)
    cache(policy).write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "rows": rows}, indent=1))
    print(f"wrote {cache(policy)}")


def markdown(results: dict[str, dict]) -> str:
    out = [
        "# OpenFOAM recovery ladder: evaluation",
        "",
        "Generated by `scripts/of_recovery.py report` from `evals/openfoam_recovery_<policy>.json`. Each case is a "
        "design whose L0 setup fails; the ladder (`swarm/solvers/openfoam/recovery.py`) then runs as in a graph run. "
        "Policies: deterministic (failure-class preference) and llm (the CFD agent choosing levels; code forbids "
        "repeats and bounds the ladder).",
        "",
        "| case | what fails | policy | L0 signature (class) | levels tried | result | Cl | Cd | wall clock |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for policy, data in results.items():
        for r in data["rows"]:
            if "error" in r:
                out.append(f"| {r['case']} | | {policy} | error: {r['error'][:80]} | | | | | |")
                continue
            levels = " → ".join(f"L{a['level']}" for a in r["attempts"])
            res = "recovered" if r["recovered"] else ("no failure at L0" if not r["l0_failed"] else r["final_status"])
            if r["attempts"][-1].get("unsimulatable"):
                res = "unsimulatable at of2d (XFoil fallback)"
            cl = "—" if r["cl"] is None else f"{r['cl']:.4f}"
            cd = "—" if r["cd"] is None else f"{r['cd']:.5f}"
            out.append(
                f"| {r['case']} | {r['description']} | {policy} | `{r['l0_signature']}` ({r['l0_class']}) | {levels} "
                f"| {res} | {cl} | {cd} | {r['wall_s']:.0f} s |"
            )
    out += ["", "Levels: " + "; ".join(f"L{k} {v}" for k, v in __import__("swarm.solvers.openfoam.recovery",
            fromlist=["LEVELS"]).LEVELS.items()) + ".", ""]  # fmt: skip
    out += ["## LLM rationales", ""]
    for r in results.get("llm", {}).get("rows", []):
        for a in r.get("attempts", [])[1:]:
            out.append(f"- {r['case']}, L{a['level']}: {a.get('rationale', '')}")
    out.append("")
    return "\n".join(out)


def cmd_report() -> None:
    results = {p: json.loads(cache(p).read_text()) for p in ("deterministic", "llm") if cache(p).exists()}
    keep = ""
    if DOC.exists() and "## Findings" in DOC.read_text():
        keep = "\n" + DOC.read_text()[DOC.read_text().index("## Findings") :]
    DOC.write_text(markdown(results) + keep)
    print(f"wrote {DOC}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--policy", choices=("deterministic", "llm"), required=True)
    r.add_argument("--parallel", type=int, default=3)
    r.add_argument("--cases", nargs="+", default=list(CASES))
    sub.add_parser("report")
    a = ap.parse_args()
    cmd_run(a.policy, a.parallel, a.cases) if a.cmd == "run" else cmd_report()
