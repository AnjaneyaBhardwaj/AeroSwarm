"""NeuralFoil-tier screen: stall margin (alpha+1, +2) and a suction-side separation warning.

Runs in one surrogate call (milliseconds) for every candidate with a physical result.
At NeuralFoil fidelity a failed screen is a `neuralfoil_screen` check (TARGET_MISS) and
blocks promotion of that candidate to XFoil. At XFoil it is only compared with XFoil's own
stall-margin probe and TE-separation check, which stay authoritative; any disagreement is
logged. Thresholds and their calibration: `ValidatorConfig.screen_*`.
"""

from __future__ import annotations

import math

import neuralfoil as nf

from swarm.critic.numeric import VALIDATION, ValidatorConfig
from swarm.solvers import neuralfoil
from swarm.state import CFDResult, DesignSpec, StallMargin, SurrogateScreen, WingParams

BL_X = [float(x) for x in nf.bl_x_points]


def _te_run_start(h: list[float], h_sep: float, xtr: float) -> float | None:
    """x/c where the run of H >= h_sep that reaches the last station starts (after transition)."""
    start = None
    for x, v in zip(reversed(BL_X), reversed(h), strict=True):
        if x < xtr or not (math.isfinite(v) and v >= h_sep):
            break
        start = x
    return start


def surrogate_screen(params: WingParams, spec: DesignSpec, cfg: ValidatorConfig = VALIDATION) -> SurrogateScreen:
    alphas = [params.alpha_deg] + [round(params.alpha_deg + d, 4) for d in cfg.stall_probe_deg]
    pol = neuralfoil.polar(params, spec, alphas)
    cls = [float(c) for c in pol["cl"]]
    h_te = [float(row[-1]) for row in pol["upper_h"]]
    finite = all(math.isfinite(v) for v in cls + h_te)
    pts = list(zip(alphas, cls, strict=True))
    slopes = [(abs(c1) - abs(c0)) / (a1 - a0) for (a0, c0), (a1, c1) in zip(pts, pts[1:], strict=False)]
    margin = min(slopes) if finite and slopes else None
    stall_ok = margin is not None and margin >= cfg.screen_min_dcl_dalpha
    sep_xc = _te_run_start([float(v) for v in pol["upper_h"][0]], cfg.screen_h_sep, float(pol["xtr_upper"][0]))
    sep_warning = not finite or sep_xc is not None
    return SurrogateScreen(
        alphas_deg=alphas,
        cls=[round(c, 5) for c in cls],
        slopes=[round(v, 5) for v in slopes],
        dcl_dalpha=None if margin is None else round(margin, 5),
        stall_threshold=cfg.screen_min_dcl_dalpha,
        stall_ok=stall_ok,
        te_shape_factor=[round(v, 3) for v in h_te],
        sep_xc=sep_xc,
        h_sep=cfg.screen_h_sep,
        sep_warning=sep_warning,
        ok=stall_ok and not sep_warning,
    )


def compare_with_xfoil(screen: SurrogateScreen, result: CFDResult, stall: StallMargin | None) -> dict:
    """What the screen predicted vs what XFoil found for the same geometry.

    stall: screen.stall_ok vs the XFoil probe's ok (only when the probe measured a slope).
    separation: screen.sep_warning vs XFoil TE separation at the design alpha.
    """
    out: dict = {"disagree": []}
    if stall is not None and stall.dcl_dalpha is not None:
        out["stall"] = {
            "screen_ok": screen.stall_ok,
            "screen_dcl_dalpha": screen.dcl_dalpha,
            "xfoil_ok": stall.ok,
            "xfoil_dcl_dalpha": stall.dcl_dalpha,
        }
        if screen.stall_ok != stall.ok:
            out["disagree"].append("stall")
    xsep = result.bl.te_separation_xc if result.bl is not None else None
    if result.bl is not None:
        out["separation"] = {
            "screen_warning": screen.sep_warning,
            "screen_h_te": screen.te_shape_factor[0] if screen.te_shape_factor else None,
            "xfoil_te_separation_xc": xsep,
        }
        if screen.sep_warning != (xsep is not None):
            out["disagree"].append("separation")
    return out
