"""T0: NeuralFoil surrogate (milliseconds per evaluation, runs offline)."""

from __future__ import annotations

import time

import aerosandbox as asb
import neuralfoil as nf
import numpy as np

from swarm.cad.build import main_section
from swarm.state import CFDResult, DesignSpec, Fidelity, WingParams

MODEL_SIZE = "large"


def _aero(params: WingParams, spec: DesignSpec) -> dict:
    af = asb.Airfoil(name=params.cid, coordinates=main_section(params))
    return nf.get_aero_from_airfoil(
        airfoil=af, alpha=params.alpha_deg, Re=spec.reynolds, n_crit=spec.ncrit, model_size=MODEL_SIZE
    )


def _f(x) -> float:
    return float(np.ravel(x)[0])


def evaluate(params: WingParams, spec: DesignSpec, fallback_from: Fidelity | None = None) -> CFDResult:
    t0 = time.perf_counter()
    r = _aero(params, spec)
    return CFDResult(
        cid=params.cid,
        fidelity="neuralfoil",
        status="converged",
        cl=-_f(r["CL"]),  # upright section simulated; race-car Cl is negated
        cd=_f(r["CD"]),
        cm=-_f(r["CM"]),
        confidence=_f(r["analysis_confidence"]),
        fallback_from=fallback_from,
        wall_s=time.perf_counter() - t0,
    )


def coefficients(params: WingParams, spec: DesignSpec) -> tuple[float, float]:
    r = _aero(params, spec)
    return -_f(r["CL"]), _f(r["CD"])


def sensitivities(
    params: WingParams, spec: DesignSpec, names: list[str] | tuple[str, ...], rel_step: float = 0.02
) -> dict[str, dict[str, float]]:
    """Central finite differences of race-car (Cl, Cd) per unit parameter change.

    Steps are `rel_step` of each parameter's range; one-sided at a bound.
    """
    bounds = WingParams.bounds()
    out: dict[str, dict[str, float]] = {}
    base = params.model_dump()
    for n in names:
        lo, hi = bounds[n]
        h = rel_step * (hi - lo)
        v = base[n]
        a, b = max(lo, v - h), min(hi, v + h)
        if b - a < 1e-6:
            continue
        cl_a, cd_a = coefficients(WingParams(**{**base, n: a}), spec)
        cl_b, cd_b = coefficients(WingParams(**{**base, n: b}), spec)
        # Use the quantized step actually evaluated.
        da = WingParams(**{**base, n: b}).model_dump()[n] - WingParams(**{**base, n: a}).model_dump()[n]
        out[n] = {"dCl": (cl_b - cl_a) / da, "dCd": (cd_b - cd_a) / da}
    return out
