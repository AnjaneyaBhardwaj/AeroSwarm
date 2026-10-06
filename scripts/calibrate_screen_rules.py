"""Compare NeuralFoil stall-screen rules against XFoil's stall gate on the gated sweep.

    uv run python scripts/gated_sweep.py run runs_gated gated.json   # XFoil sweep (~11 min, 4 cores)
    uv run python scripts/calibrate_screen_rules.py gated.json

Ground truth per sweep point (alpha a, a+1 and a+2 converged): XFoil's gate = attached at a, no TE
separation at a+1/a+2, d|Cl|/dalpha >= 0.05/deg over a..a+2 (`gated_sweep.gate`, geometry checks
included). The screen sees only NeuralFoil: its slopes s1 (a->a+1), s2 (a+1->a+2), s3 (a+2->a+3) and
the suction-side TE shape factor at a (separation warning, unchanged here).

Rules, each also applying the separation warning:
  (a) slope:  min(s1, s2) >= T
  (b) +3 probe: min(s1, s2, s3) >= T
  (c) knee:   min(s1, s2) >= 0.05 and s1 - s2 <= X   (fail when the second segment drops by > X)
  (c') knee:  min(s1, s2) >= T and s1 - s2 <= X      (both, small grid)
  (d) probe separation: min(s1, s2) >= T and NeuralFoil TE H at a+1 and a+2 < Hmax (XFoil's gate
      also fails on TE separation at the probes; 22 of the 50 window false passes of the old rule
      were exactly that)

Population "window": what the screen gates in the pipeline: NeuralFoil |Cl| within 2*cl_tol of the
hard target and NeuralFoil Cd <= cd_max (`briefs.promotable`). "all": every evaluable point.
false pass = share of screen passes that fail XFoil's gate; false block = XFoil passes the screen blocks.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import aerosandbox as asb
import neuralfoil as nf
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import gated_sweep  # noqa: E402

from swarm.briefs import NEAR_TARGET_FACTOR  # noqa: E402
from swarm.cad.build import main_section  # noqa: E402
from swarm.critic.numeric import VALIDATION  # noqa: E402
from swarm.run import HARD_SPEC  # noqa: E402
from swarm.state import WingParams  # noqa: E402

# Cost-weighted criterion (session 10): a false pass costs one XFoil evaluation, a false block may lose
# the feasible design. Pick the fewest blocks with a false-pass rate in [FP_LO, FP_HI]; also report the
# setting minimising false passes + W * blocks for a few weights W (XFoil evals per lost design).
FP_LO, FP_HI = 0.15, 0.20
WEIGHTS = (3, 5, 10)


def neuralfoil_table(rows: list[dict]) -> dict:
    """NeuralFoil Cl, Cd and suction-side TE H at every sweep alpha and +3 deg beyond."""
    by: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        by[(r["m"], r["p"], r["t"])].append(r["a"])
    out = {}
    for (m, p, t), als in by.items():
        grid = sorted(set(als) | {round(a + d, 2) for a in als for d in (1.0, 2.0, 3.0)})
        wp = WingParams(main_camber=m, main_camber_pos=p, main_thickness=t, alpha_deg=grid[0])
        af = asb.Airfoil(name=wp.cid, coordinates=main_section(wp))
        r = nf.get_aero_from_airfoil(
            airfoil=af, alpha=np.array(grid), Re=HARD_SPEC.reynolds, n_crit=HARD_SPEC.ncrit, model_size="large"
        )
        h = np.ravel(r[f"upper_bl_H_{len(nf.bl_x_points) - 1}"])
        for i, a in enumerate(grid):
            out[(m, p, t, a)] = (-float(np.ravel(r["CL"])[i]), float(np.ravel(r["CD"])[i]), float(h[i]))
    return out


def points(path: str) -> list[dict]:
    # legal sections only (gated_sweep.load: t >= the rulebook's floor); comma-separated files allowed
    gated = [g for g in gated_sweep.gate(gated_sweep.load(path)) if g["margin"] is not None]
    nfd = neuralfoil_table(gated)
    out = []
    for g in gated:
        k = (g["m"], g["p"], g["t"])
        cl = [abs(nfd[(*k, round(g["a"] + d, 2))][0]) for d in (0.0, 1.0, 2.0, 3.0)]
        s1, s2, s3 = cl[1] - cl[0], cl[2] - cl[1], cl[3] - cl[2]
        ncl, ncd, h = nfd[(*k, g["a"])]
        h1, h2 = nfd[(*k, round(g["a"] + 1.0, 2))][2], nfd[(*k, round(g["a"] + 2.0, 2))][2]
        window = abs(ncl - HARD_SPEC.target_cl) <= NEAR_TARGET_FACTOR * HARD_SPEC.cl_tol and ncd <= HARD_SPEC.cd_max
        sep = h >= VALIDATION.screen_h_sep
        out.append(dict(s1=s1, s2=s2, s3=s3, hp=max(h1, h2), sep=sep, window=window, xfoil=g["passes"]))
    return out


def score(pts: list[dict], rule) -> tuple[int, int, int, int]:
    """(screen passes, of which XFoil fails, XFoil passes, of which the screen blocks)."""
    sp = [p for p in pts if not p["sep"] and rule(p)]
    xp = [p for p in pts if p["xfoil"]]
    return len(sp), sum(not p["xfoil"] for p in sp), len(xp), sum(p["sep"] or not rule(p) for p in xp)


def line(name: str, s: tuple[int, int, int, int]) -> str:
    n, fp, nx, fb = s
    rate = fp / n if n else float("nan")
    return (
        f"{name:<34} passes {n:4d}  false pass {fp:4d} ({rate:5.1%})  "
        f"blocks {fb:4d} of {nx:4d} XFoil passes ({fb / nx:5.1%})"
    )


def best(pts: list[dict], family: dict) -> tuple[str, tuple] | None:
    """Fewest false blocks among settings with a false-pass rate in [FP_LO, FP_HI] (then fewer false passes)."""
    ok = [(name, score(pts, rule)) for name, rule in family.items()]
    ok = [(n, s) for n, s in ok if s[0] and FP_LO <= s[1] / s[0] <= FP_HI]
    return min(ok, key=lambda x: (x[1][3], x[1][1])) if ok else None


def cheapest(pts: list[dict], family: dict, w: float) -> tuple[str, tuple]:
    """Minimum false passes + w * false blocks."""
    scored = [(name, score(pts, rule)) for name, rule in family.items()]
    return min(scored, key=lambda x: (x[1][1] + w * x[1][3], x[1][3]))


def main(path: str) -> None:
    pts = points(path)
    lo = VALIDATION.stall_min_dcl_dalpha

    def slope(t):
        return lambda p: min(p["s1"], p["s2"]) >= t

    def plus3(t):
        return lambda p: min(p["s1"], p["s2"], p["s3"]) >= t

    def knee(t, x):
        return lambda p: min(p["s1"], p["s2"]) >= t and p["s1"] - p["s2"] <= x

    def probe_h(t, hm):
        return lambda p: min(p["s1"], p["s2"]) >= t and p["hp"] < hm

    grid = np.arange
    fams = {
        "(a) slope": {f"min(s1,s2) >= {t:.3f}": slope(t) for t in grid(0.05, 0.1201, 0.005)},
        "(b) +3 probe": {f"min(s1,s2,s3) >= {t:.3f}": plus3(t) for t in grid(0.03, 0.1001, 0.005)},
        "(c) knee": {f"0.05 & s1-s2 <= {x:.3f}": knee(lo, x) for x in grid(0.0, 0.0601, 0.0025)},
        "(c') slope+knee": {
            f"min >= {t:.3f} & drop <= {x:.3f}": knee(t, x)
            for t in grid(0.05, 0.0801, 0.005)
            for x in grid(0.0, 0.0401, 0.005)
        },
        "(d) slope+probe H": {
            f"min >= {t:.4f} & H(a+1,a+2) < {hm:.2f}": probe_h(t, hm)
            for t in grid(0.05, 0.0701, 0.0025)
            for hm in grid(3.4, 4.61, 0.05)
        },
    }
    for pop, sel in (("window", [p for p in pts if p["window"]]), ("all", pts)):
        print(f"\n=== population {pop}: {len(sel)} points, {sum(p['xfoil'] for p in sel)} pass XFoil's gate")
        print(line("session-6 rule: min(s1,s2) >= 0.050", score(sel, lambda p: min(p["s1"], p["s2"]) >= lo)))
        cur_t, cur_h = VALIDATION.screen_min_dcl_dalpha, VALIDATION.screen_h_probe_max
        print(line(f"current: >= {cur_t} & H(a+1,a+2) < {cur_h}", score(sel, probe_h(cur_t, cur_h))))
        for fam, rules in fams.items():
            b = best(sel, rules)
            print(
                line(f"{fam} best: {b[0]}", b[1]) if b else f"{fam}: no setting in {FP_LO:.0%}-{FP_HI:.0%} false pass"
            )
        if pop == "window":
            for w in WEIGHTS:
                for fam in ("(a) slope", "(d) slope+probe H"):
                    n, sc = cheapest(sel, fams[fam], w)
                    print(line(f"  cost FP+{w}*FB, {fam}: {n}", sc))
        if pop == "window":
            for fam in ("(a) slope", "(b) +3 probe", "(c) knee"):
                print(f"  {fam} sweep:")
                for name, rule in fams[fam].items():
                    print("    " + line(name, score(sel, rule)))


if __name__ == "__main__":
    main(sys.argv[1])
