"""Shared fixtures. Tests run offline: mock/scripted LLM, NeuralFoil (bundled
weights), recorded XFoil output, and a fake XFoil evaluator for graph tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.solvers import neuralfoil
from swarm.state import CFDResult, DesignSpec, StallMargin, WingParams, speed_for_reynolds

FIXTURES = Path(__file__).parent / "fixtures"


def good_stall(alpha=9.5, slope=0.09) -> StallMargin:
    """A passing stall-margin probe for tests that need a candidate to reach target_met."""
    return StallMargin(
        alphas_deg=[alpha, alpha + 1, alpha + 2],
        cls=[-1.5, -1.5 - slope, -1.5 - 2 * slope],
        levels=[0, 0, 0],
        slopes=[slope, slope],
        dcl_dalpha=slope,
        threshold=0.05,
        ok=True,
    )


@pytest.fixture
def spec() -> DesignSpec:
    return DesignSpec(
        component="wing_1el",
        target_cl=-1.50,
        cl_tol=0.03,
        cd_max=0.018,
        speed_mps=speed_for_reynolds(8.3e5, 300.0),
        max_evals=30,
    )


@pytest.fixture
def start() -> WingParams:
    return WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.13, alpha_deg=4.0)  # FSAE: t >= 0.123


@pytest.fixture
def fake_xfoil(monkeypatch):
    """Replace XFoil with a NeuralFoil-backed stand-in (a cached-solver substitute).

    `fail_levels`: ladder levels that report not_converged. `cl_offset` shifts
    Cl to emulate a fidelity gap. `flat_probes` makes the stall-margin probes return the
    design-point Cl (zero slope). Returns the list of (cid, level) calls.
    """

    def install(fail_levels=(), cl_offset=0.0, flat_probes=False):
        calls = []

        def evaluate(params, spec, coords_path, run_dir, level, alpha_deg=None):
            calls.append((params.cid, level) if alpha_deg is None else (params.cid, level, alpha_deg))
            design_alpha = params.alpha_deg
            if alpha_deg is not None:  # stall-margin probe: same geometry at another alpha
                params = params.model_copy(update={"alpha_deg": alpha_deg})
            if level in fail_levels:
                return CFDResult(
                    cid=params.cid,
                    fidelity="xfoil",
                    status="not_converged",
                    solver_level=level,
                    failure_signature=f"not_converged@L{level}",
                )
            r = neuralfoil.evaluate(params, spec)
            if flat_probes and alpha_deg is not None:  # emulate Cl,max: no gain from the extra alpha
                r = neuralfoil.evaluate(params.model_copy(update={"alpha_deg": design_alpha}), spec)
            return r.model_copy(
                update={"fidelity": "xfoil", "solver_level": level, "confidence": None, "cl": r.cl + cl_offset}
            )

        monkeypatch.setattr("swarm.solvers.xfoil.evaluate", evaluate)
        return calls

    return install
