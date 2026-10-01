"""Calibrate the NeuralFoil screen against the XFoil sweep at the hard preset's Re.

Reproduces the numbers behind `ValidatorConfig.screen_min_dcl_dalpha` and `screen_h_sep`
(docs/PROGRESS.md, session 6):

    uv run python scripts/clmax_sweep.py runs_sweep sweep.json   # XFoil, ~30 s on 4 cores
    uv run python scripts/calibrate_screen.py sweep.json

Separation: XFoil TE separation (suction-side Cf < 0 persisting to the TE) vs NeuralFoil's
suction-side shape factor H at its last station (x/c 0.984), at the same point.
Stall: XFoil's d|Cl|/dalpha margin over alpha..alpha+2 (passes at >= stall_min_dcl_dalpha)
vs the same margin on NeuralFoil's Cl. "Near target" = |XFoil Cl| within 0.06 of 1.78.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

import aerosandbox as asb
import neuralfoil as nf
import numpy as np

from swarm.cad.build import main_section
from swarm.critic.numeric import VALIDATION
from swarm.run import HARD_SPEC
from swarm.state import WingParams

NEAR = 0.06


def _margin(alphas: list[float], cls: list[float]) -> float:
    pts = list(zip(alphas, cls, strict=True))
    return min((abs(c1) - abs(c0)) / (a1 - a0) for (a0, c0), (a1, c1) in zip(pts, pts[1:], strict=False))


def _confusion(pred: np.ndarray, truth: np.ndarray) -> str:
    tp, fp = int((pred & truth).sum()), int((pred & ~truth).sum())
    fn, tn = int((~pred & truth).sum()), int((~pred & ~truth).sum())
    rec = tp / (tp + fn) if tp + fn else float("nan")
    spec = tn / (tn + fp) if tn + fp else float("nan")
    return f"TP {tp:4d} FP {fp:4d} FN {fn:4d} TN {tn:4d}  recall {rec:.2f} specificity {spec:.2f}"


def main(path: str) -> None:
    rows = [r for r in json.loads(open(path).read()) if r["status"] == "ok"]
    geo: dict[tuple, dict] = defaultdict(dict)
    for r in rows:
        geo[(r["m"], r["p"], r["t"])][r["a"]] = r
    nfd = {}
    for (m, p, t), pts in geo.items():
        alphas = sorted(pts)
        wp = WingParams(main_camber=m, main_camber_pos=p, main_thickness=t, alpha_deg=alphas[0])
        af = asb.Airfoil(name=wp.cid, coordinates=main_section(wp))
        out = nf.get_aero_from_airfoil(
            airfoil=af, alpha=np.array(alphas), Re=HARD_SPEC.reynolds, n_crit=HARD_SPEC.ncrit, model_size="large"
        )
        h_te = np.ravel(out[f"upper_bl_H_{len(nf.bl_x_points) - 1}"])
        for j, a in enumerate(alphas):
            nfd[(m, p, t, a)] = (float(np.ravel(out["CL"])[j]), float(h_te[j]))

    sep = np.array([r["sep"] is not None for r in rows])
    h = np.array([nfd[(r["m"], r["p"], r["t"], r["a"])][1] for r in rows])
    near = np.array([abs(abs(r["cl"]) - abs(HARD_SPEC.target_cl)) <= NEAR for r in rows])
    th = VALIDATION.screen_h_sep
    print(f"Separation, H_te >= {th}: {len(rows)} points, {sep.sum()} XFoil TE-separated")
    print(f"  all:         {_confusion(h >= th, sep)}")
    print(f"  near target: {_confusion(h[near] >= th, sep[near])}")
    best = max(np.arange(2.0, 8.01, 0.25), key=lambda x: 0.5 * ((h >= x)[sep].mean() + (h < x)[~sep].mean()))
    print(f"  best balanced accuracy over 2.0-8.0 (0.25 steps): H_te >= {best:.2f}")

    xs, ns, nr = [], [], []
    for (m, p, t), pts in geo.items():
        for a in sorted(pts):
            al = [a + d for d in (0.0, *VALIDATION.stall_probe_deg)]
            if all(x in pts for x in al):
                xs.append(_margin(al, [pts[x]["cl"] for x in al]))
                ns.append(_margin(al, [nfd[(m, p, t, x)][0] for x in al]))
                nr.append(abs(abs(pts[a]["cl"]) - abs(HARD_SPEC.target_cl)) <= NEAR and pts[a]["sep"] is None)
    xs, ns, nr = np.array(xs), np.array(ns), np.array(nr)
    xfail = xs < VALIDATION.stall_min_dcl_dalpha
    nblock = ns < VALIDATION.screen_min_dcl_dalpha
    print(f"\nStall, NeuralFoil margin < {VALIDATION.screen_min_dcl_dalpha} blocks (positive = XFoil margin fails):")
    print(f"  all ({len(xs)} points):              {_confusion(nblock, xfail)}")
    print(f"  near target, attached ({nr.sum()} points): {_confusion(nblock[nr], xfail[nr])}")


if __name__ == "__main__":
    main(sys.argv[1])
