"""Shared fixtures. Tests run offline: mock/scripted LLM, NeuralFoil (bundled
weights), recorded XFoil output, and a fake XFoil evaluator for graph tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.solvers import neuralfoil
from swarm.state import CFDResult, DesignSpec, WingParams, speed_for_reynolds

FIXTURES = Path(__file__).parent / "fixtures"


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
    return WingParams(main_camber=0.02, main_camber_pos=0.40, main_thickness=0.12, alpha_deg=4.0)


@pytest.fixture
def fake_xfoil(monkeypatch):
    """Replace XFoil with a NeuralFoil-backed stand-in (a cached-solver substitute).

    `fail_levels`: ladder levels that report not_converged. `cl_offset` shifts
    Cl to emulate a fidelity gap. Returns the list of (cid, level) calls.
    """

    def install(fail_levels=(), cl_offset=0.0):
        calls = []

        def evaluate(params, spec, coords_path, run_dir, level):
            calls.append((params.cid, level))
            if level in fail_levels:
                return CFDResult(
                    cid=params.cid,
                    fidelity="xfoil",
                    status="not_converged",
                    solver_level=level,
                    failure_signature=f"not_converged@L{level}",
                )
            r = neuralfoil.evaluate(params, spec)
            return r.model_copy(
                update={"fidelity": "xfoil", "solver_level": level, "confidence": None, "cl": r.cl + cl_offset}
            )

        monkeypatch.setattr("swarm.solvers.xfoil.evaluate", evaluate)
        return calls

    return install
