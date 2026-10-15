"""XFoil failure zoo for the recovery ladder (milestone 2; swarm/evals/zoo.py).

    uv run python scripts/failure_zoo.py run --parallel 4   # needs xfoil; writes evals/xfoil_zoo.json
    uv run python scripts/failure_zoo.py report             # writes docs/FAILURE_ZOO.md from the cache

Every case is solved at every ladder level, at the hard preset's Reynolds number and Ncrit, with the
rulebook check off (the zoo includes sections thinner than FSAE 2027 allows; the table marks them).
Solver work files go to runs/zoo/ (not committed).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from swarm.cad.build import build
from swarm.evals import zoo
from swarm.run import HARD_SPEC
from swarm.solvers import neuralfoil, xfoil

SPEC = HARD_SPEC.model_copy(update={"rulebook": "none"})
CACHE = Path("evals/xfoil_zoo.json")
DOC = Path("docs/FAILURE_ZOO.md")
WORK = Path("runs/zoo")


def one(case: dict) -> dict:
    geo = build(case["params"], SPEC, WORK)

    def solve(p, level):
        return xfoil.evaluate(p, SPEC, geo.coords_path, WORK, level)

    return zoo.run_case(case, solve, lambda p: neuralfoil.evaluate(p, SPEC))


def cmd_run(parallel: int) -> None:
    if not xfoil.xfoil_available():
        sys.exit("xfoil not found (scripts/install_xfoil.sh)")
    cs = zoo.cases()
    t0 = time.time()
    with Pool(parallel) as pool:
        results = []
        for r in pool.imap(one, cs):
            o = zoo.outcome(r)
            print(f"{r['name']}: {zoo.label(o)}", flush=True)
            results.append(r)
    meta = {
        "date": time.strftime("%Y-%m-%d"),
        "reynolds": SPEC.reynolds,
        "ncrit": SPEC.ncrit,
        "wall_s": round(time.time() - t0, 1),
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"meta": meta, "results": results}, indent=1))
    print(f"wrote {CACHE} ({len(results)} cases, {meta['wall_s']:.0f} s)")


def cmd_report() -> None:
    data = json.loads(CACHE.read_text())
    keep = ""
    if DOC.exists() and "## Findings" in DOC.read_text():  # hand-written; survives regeneration
        keep = "\n" + DOC.read_text()[DOC.read_text().index("## Findings") :]
    DOC.write_text(zoo.markdown(data["results"], data["meta"]) + keep)
    print(f"wrote {DOC}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--parallel", type=int, default=4)
    sub.add_parser("report")
    a = ap.parse_args()
    if a.cmd == "run":
        cmd_run(a.parallel)
    else:
        cmd_report()


if __name__ == "__main__":
    main()
