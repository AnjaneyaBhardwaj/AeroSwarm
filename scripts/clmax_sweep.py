"""Attached Cl_max over the feasible single-element box at the hard preset's Re.

Reproduces the session-3 numbers (docs/PROGRESS.md, session 3), under the Formula Student 2026
rulebook used then; the project now uses FSAE 2027 (thickness floor 0.123, scripts/gated_sweep.py).

    uv run python scripts/clmax_sweep.py runs_sweep sweep.json   # XFoil, 4 processes
    uv run python scripts/clmax_sweep.py --analyze sweep.json

Each point walks the same XFoil recovery ladder as the wrapper. Thickness starts at
the FS2026 LE-radius floor (0.0953 on a 300 mm chord), because thinner sections are
rejected by `build()` and cannot be candidates. "Attached" = converged with no
suction-side Cf < 0 persisting to the TE, in the unbroken alpha run starting at the
lowest alpha: the first separated or unconverged alpha ends it.
"""

from __future__ import annotations

import itertools
import json
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from swarm.cad.build import main_section, write_coords
from swarm.run import HARD_SPEC
from swarm.solvers import xfoil
from swarm.state import WingParams

CAMBER = (0.06, 0.075, 0.09)
POS = (0.2, 0.3, 0.4, 0.5)
THICK = (0.0955, 0.12, 0.15, 0.18)
ALPHAS = tuple(float(a) for a in np.arange(4.0, 14.01, 0.5))


def _one(job):
    work, m, p, t, a = job
    wp = WingParams(main_camber=m, main_camber_pos=p, main_thickness=t, alpha_deg=a)
    d = Path(work) / wp.cid
    coords = write_coords(main_section(wp), d / "in.dat", wp.cid)
    row = dict(m=m, p=p, t=t, a=a, status="fail")
    for lvl in range(xfoil.MAX_LEVEL + 1):
        r = xfoil.run_xfoil(coords, HARD_SPEC.reynolds, a, lvl, d / f"a{a:+.1f}_L{lvl}", ncrit=HARD_SPEC.ncrit)
        if r["status"] == "converged":
            bl = xfoil.summarize_bl(r["dump"], r["cl"], r) if r.get("dump") is not None else None
            row |= dict(status="ok", level=lvl, cl=r["cl"], cd=r["cd"], sep=bl.te_separation_xc if bl else None)
            break
    return row


def run_sweep(work: str, out: str) -> None:
    jobs = [(work, m, p, t, a) for m, p, t in itertools.product(CAMBER, POS, THICK) for a in ALPHAS]
    with Pool(4) as pool:
        rows = pool.map(_one, jobs, chunksize=8)
    Path(out).write_text(json.dumps(rows))
    print(f"{len(rows)} XFoil points at Re {HARD_SPEC.reynolds:.3g}, {sum(r['status'] == 'fail' for r in rows)} failed")


def analyze(path: str) -> None:
    by: dict[tuple, list[dict]] = defaultdict(list)
    for r in json.loads(Path(path).read_text()):
        by[(r["m"], r["p"], r["t"])].append(r)
    best = []
    for key, rows in by.items():
        rows.sort(key=lambda r: r["a"])
        att = []
        for r in rows:
            if r["status"] != "ok" or r["sep"] is not None:
                break
            att.append(r)
        if att:
            peak = max(att, key=lambda r: r["cl"])
            best.append((peak["cl"], key, peak, rows[len(att)] if len(att) < len(rows) else None))
    best.sort(key=lambda b: -b[0])
    print("attached Cl_max by section (upright Cl; race-car Cl is its negative)")
    for cl, (m, p, t), pk, nxt in best[:10]:
        end = "end of sweep" if nxt is None else f"next alpha {nxt['a']}: {nxt['status']}, sep={nxt.get('sep')}"
        print(f"  m={m} p={p} t={t}: Cl {cl:.3f} Cd {pk['cd']:.4f} @ alpha {pk['a']}  ({end})")
    top = best[0][0]
    print(f"attached Cl_max = {top:.3f}; 85% = {0.85 * top:.3f}")


if __name__ == "__main__":
    if sys.argv[1] == "--analyze":
        analyze(sys.argv[2])
    else:
        run_sweep(sys.argv[1], sys.argv[2])
