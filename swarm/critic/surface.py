"""Surface data of a solver result, and two deterministic consistency measures on it (milestone 3).

The Critic evaluation (docs/CRITIC_EVAL.md) found that a vision LLM shown the Cp plot did not notice
coefficients inconsistent with that plot, nor a local spike from a geometry defect. Both are numbers:
- `cl_from_cp`: race-car Cl integrated from the surface pressure (pressure force only, in body axes, rotated
  by alpha). Against the reported Cl: XFoil within 0.0044 on 59 random FSAE-legal designs; NeuralFoil within
  ±10% (its 32 stations start at x/c 0.016 and miss part of the leading-edge suction peak).
- `cp_spike`: prominence of the largest narrow (< 0.04 c wide) local maximum of -Cp on the suction side aft of
  x/c 0.05. Clean XFoil solutions: at most 0.035 on 118 random designs plus the zoo cases; a 0.4% c bump:
  0.54-0.67. NeuralFoil's station spacing (0.03 c) cannot resolve it, so it is XFoil only.

Surface data: OpenFOAM (of2d) from the wall-adjacent cells (swarm.solvers.openfoam.forces); XFoil from the
result's boundary-layer dump (Ue/Vinf, Cf, H at every panel node; Cp = 1 - Ue²);
NeuralFoil from one surrogate call (Ue/Vinf and H at 32 stations per side). The solver runs the section
upright; the upright upper surface is the suction side of the race-car wing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from swarm.cad.build import main_section
from swarm.state import CFDResult, DesignSpec, WingParams

SPIKE_MAX_WIDTH = 0.04  # x/c: a feature narrower than this is a spike, not a pressure hump
SPIKE_X_MIN = 0.05  # aft of the leading-edge suction peak


def surface_data(params: WingParams, spec: DesignSpec | None, result: CFDResult | None) -> dict | None:
    """{"suction": {x, cp, h, cf?}, "pressure": {x, cp, h, cf?}, "source"} or None if the result has none."""
    if result is None or result.cl is None:
        return None
    if result.fidelity == "xfoil":
        return _xfoil_surface(result)
    if result.fidelity == "of2d":
        return _openfoam_surface(params, spec, result)
    return _neuralfoil_surface(params, spec)


def _openfoam_surface(params: WingParams, spec: DesignSpec, result: CFDResult) -> dict | None:
    from swarm.solvers.openfoam import forces

    case = result.artifacts.get("case")
    if not case or not Path(case).exists():
        return None
    dirs = forces.time_dirs(case)
    if not dirs:
        return None
    span = forces.span_of(case)
    c = forces.coefficients(case, dirs[-1][1], params.alpha_deg, spec.reynolds, span)
    return forces.surface(c, c["cl"])


def _xfoil_surface(result: CFDResult) -> dict | None:
    from swarm.solvers.xfoil import NonFiniteDump, parse_dump

    path = result.artifacts.get("bl_dump")
    if not path or not Path(path).exists():
        return None
    try:
        dump = parse_dump(Path(path).read_text())
    except NonFiniteDump:
        return None
    if dump is None:
        return None
    raw = dump.raw  # columns: s, x, y, Ue/Vinf, Dstar, Theta, Cf, H; TE(upper) -> LE -> TE(lower)
    ile = int(np.argmin(raw[:, 1]))
    up, lo = raw[: ile + 1][::-1], raw[ile:]

    def side(a: np.ndarray) -> dict:
        return {"x": a[:, 1], "cp": 1.0 - a[:, 3] ** 2, "h": a[:, 7], "cf": a[:, 6]}

    suction = "upper" if (result.bl is None or result.bl.suction_side == "upper") else "lower"
    s, p = (side(up), side(lo)) if suction == "upper" else (side(lo), side(up))
    return {"suction": s, "pressure": p, "source": "XFoil boundary-layer dump"}


def _neuralfoil_surface(params: WingParams, spec: DesignSpec) -> dict:
    import aerosandbox as asb
    import neuralfoil as nf

    from swarm.solvers.neuralfoil import MODEL_SIZE

    af = asb.Airfoil(name=params.cid, coordinates=main_section(params))
    r = nf.get_aero_from_airfoil(
        airfoil=af, alpha=params.alpha_deg, Re=spec.reynolds, n_crit=spec.ncrit, model_size=MODEL_SIZE
    )
    x = np.asarray(nf.bl_x_points, dtype=float)
    n = len(x)

    def side(name: str) -> dict:
        ue = np.array([float(np.ravel(r[f"{name}_bl_ue/vinf_{i}"])[0]) for i in range(n)])
        h = np.array([float(np.ravel(r[f"{name}_bl_H_{i}"])[0]) for i in range(n)])
        return {"x": x, "cp": 1.0 - ue**2, "h": h}

    return {"suction": side("upper"), "pressure": side("lower"), "source": "NeuralFoil (32 stations per side)"}


def surface_for_checks(params: WingParams, spec: DesignSpec, result: CFDResult | None) -> dict | None:
    """Surface data for the validator's consistency checks; None (checks skipped) if unavailable or unreadable."""
    if result is None or result.status != "converged" or result.cl is None:
        return None
    try:
        return surface_data(params, spec, result)
    except Exception:  # a missing or malformed dump must not turn into a node error
        return None


def _sorted(d: dict) -> tuple[np.ndarray, np.ndarray]:
    x, i = np.unique(np.asarray(d["x"], dtype=float), return_index=True)
    return x, np.asarray(d["cp"], dtype=float)[i]


def cl_from_cp(params: WingParams, surface: dict) -> float:
    """Race-car Cl from the surface pressure: normal and axial pressure forces of the upright section (y from
    the stated geometry at each station), rotated by alpha, negated."""
    xy = main_section(params)
    ile = int(np.argmin(xy[:, 0]))
    geo = {"upper": xy[: ile + 1][::-1], "lower": xy[ile:]}
    xu, cpu = _sorted(surface["suction"])
    xl, cpl = _sorted(surface["pressure"])
    yu = np.interp(xu, geo["upper"][:, 0], geo["upper"][:, 1])
    yl = np.interp(xl, geo["lower"][:, 0], geo["lower"][:, 1])
    cn = np.trapezoid(cpl, xl) - np.trapezoid(cpu, xu)
    ca = np.trapezoid(cpu * np.gradient(yu, xu), xu) - np.trapezoid(cpl * np.gradient(yl, xl), xl)
    a = np.deg2rad(params.alpha_deg)
    return float(-(cn * np.cos(a) - ca * np.sin(a)))


def cp_spike(surface: dict) -> float:
    """Prominence of the largest narrow local maximum of -Cp on the suction side aft of SPIKE_X_MIN (0 if none)."""
    from scipy.signal import find_peaks

    x, cp = _sorted(surface["suction"])
    keep = x > SPIKE_X_MIN
    x, m = x[keep], -cp[keep]
    if len(x) < 3:
        return 0.0
    peaks, props = find_peaks(m, prominence=0.0, width=0.0)
    best = 0.0
    idx = np.arange(len(x))
    for j in range(len(peaks)):
        lo, hi = np.interp([props["left_ips"][j], props["right_ips"][j]], idx, x)
        if hi - lo < SPIKE_MAX_WIDTH:
            best = max(best, float(props["prominences"][j]))
    return best
