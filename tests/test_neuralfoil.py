import pytest

from swarm.solvers import neuralfoil
from swarm.state import WingParams

P = WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=6.0)


def test_evaluate_race_car_sign(spec):
    r = neuralfoil.evaluate(P, spec)
    assert r.status == "converged" and r.fidelity == "neuralfoil"
    assert -1.4 < r.cl < -0.9  # downforce is negative; NACA 4412 @ 6° ≈ 1.1 upright
    assert 0.005 < r.cd < 0.015
    assert r.confidence > 0.9 and not r.lower_fidelity


def test_fallback_flag(spec):
    assert neuralfoil.evaluate(P, spec, fallback_from="xfoil").lower_fidelity


def test_sensitivities_signs(spec):
    s = neuralfoil.sensitivities(P, spec, ["alpha_deg", "main_camber", "main_thickness"])
    assert s["alpha_deg"]["dCl"] < 0  # more incidence → more downforce (more negative Cl)
    assert s["main_camber"]["dCl"] < 0
    assert s["alpha_deg"]["dCl"] == pytest.approx(-0.11, abs=0.04)  # ≈ 2π per rad, viscous
