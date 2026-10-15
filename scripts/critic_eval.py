"""Critic evaluation on a labelled failure zoo (milestone 3; swarm/evals/critic_zoo.py).

    uv run python scripts/critic_eval.py build                  # needs xfoil; writes evals/critic_zoo.json
    uv run python scripts/critic_eval.py run --arms numeric     # offline: the deterministic validators alone
    uv run python scripts/critic_eval.py run --arms llm_text llm_vision   # real LLM (AEROSWARM_ANTHROPIC_API_KEY)
    uv run python scripts/critic_eval.py report                 # writes docs/CRITIC_EVAL.md

Spec: the hard preset with the rulebook check off (two wrong-branch cases are thinner than FSAE 2027
allows; the Critic does not judge legality). LLM arms log every call to evals/critic_traces_<arm>.jsonl
(not committed) and stop on the first API account error. Solver and image work files go to runs/critic_zoo/.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from swarm.cad.build import build, main_section, write_coords
from swarm.critic.render import surface_data
from swarm.evals import critic_zoo as cz
from swarm.llm.client import ACCOUNT_ERROR, AnthropicClient, TraceLogger, preflight_llm
from swarm.run import HARD_SPEC
from swarm.solvers import neuralfoil, xfoil

SPEC = HARD_SPEC.model_copy(update={"rulebook": "none"})
CASES = Path("evals/critic_zoo.json")
RESULTS = "evals/critic_results_{arm}.json"
DOC = Path("docs/CRITIC_EVAL.md")
WORK = Path("runs/critic_zoo")


def solve(p, level=0, npanel=None, kink=False):
    """XFoil at one ladder level; `npanel` overrides the level's panel count, `kink` adds a suction-side bump."""
    variant = f"L{level}" + (f"_n{npanel}" if npanel else "") + ("_kink" if kink else "")
    work = WORK / "solve" / variant
    coords = Path(build(p, SPEC, work).coords_path)
    if kink:
        xy = main_section(p).copy()
        upper = np.arange(len(xy)) < np.argmin(xy[:, 0])  # TE(upper) -> LE first: the upright suction side
        xy[upper, 1] += 0.004 * np.exp(-(((xy[upper, 0] - 0.3) / 0.02) ** 2))
        coords = write_coords(xy, work / p.cid / "coords_kink.dat", f"kink-{p.cid}")
    saved = dict(xfoil.LEVELS[level])
    if npanel:
        xfoil.LEVELS[level] = {**saved, "npanel": npanel}
    try:
        return xfoil.evaluate(p, SPEC, coords, work, level)
    finally:
        xfoil.LEVELS[level] = saved


def cmd_build() -> None:
    if not xfoil.xfoil_available():
        sys.exit("xfoil not found (scripts/install_xfoil.sh)")
    cases = cz.build_cases(SPEC, solve, lambda p, r: surface_data(p, SPEC, r), lambda p: neuralfoil.evaluate(p, SPEC))
    bad = [c["name"] for c in cases if c["result"]["status"] != "converged" or c["surface"] is None]
    if bad:
        sys.exit(f"cases without a converged result or surface data: {bad}")
    CASES.parent.mkdir(parents=True, exist_ok=True)
    CASES.write_text(json.dumps({"meta": {"built": time.strftime("%Y-%m-%d")}, "cases": cases}, indent=1))
    print(f"wrote {CASES} ({len(cases)} cases)")


def load() -> tuple[dict, list[dict]]:
    data = json.loads(CASES.read_text())
    return data["meta"], data["cases"]


def cmd_run(arms: list[str]) -> None:
    _, raw = load()
    cases = [cz.load_case(c) for c in raw]
    for arm in arms:
        llm = None
        if arm != "numeric":
            preflight_llm("anthropic")
            llm = AnthropicClient(TraceLogger(Path(f"evals/critic_traces_{arm}.jsonl")))
        rows = cz.run_arm(cases, SPEC, arm, llm, WORK / "images" / arm)
        errs = [r for r in rows if "error" in r]
        Path(RESULTS.format(arm=arm)).write_text(json.dumps(rows, indent=1))
        cost = llm.trace.summary()["cost_usd"] if llm else 0.0
        print(f"{arm}: {len(rows) - len(errs)} judged, {len(errs)} errors, est. cost ${cost:.2f}")
        if errs and any(ACCOUNT_ERROR.search(r["error"]) for r in errs):
            sys.exit(f"stopped: API account error ({errs[0]['error'][:200]})")


def cmd_report() -> None:
    meta, raw = load()
    results = {}
    for arm in cz.ARMS:
        p = Path(RESULTS.format(arm=arm))
        if p.exists():
            results[arm] = json.loads(p.read_text())
    keep = ""
    if DOC.exists() and "## Findings" in DOC.read_text():  # hand-written; survives regeneration
        keep = "\n" + DOC.read_text()[DOC.read_text().index("## Findings") :]
    DOC.write_text(cz.markdown(raw, results, meta) + keep)
    print(f"wrote {DOC}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    r = sub.add_parser("run")
    r.add_argument("--arms", nargs="+", choices=cz.ARMS, required=True)
    sub.add_parser("report")
    a = ap.parse_args()
    {"build": cmd_build, "report": cmd_report}.get(a.cmd, lambda: cmd_run(a.arms))()


if __name__ == "__main__":
    main()
