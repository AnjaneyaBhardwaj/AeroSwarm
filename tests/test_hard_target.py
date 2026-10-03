"""The hard preset's target is feasible: a witness passes the NeuralFoil screen and the full XFoil gate.

Target Cl -1.83 ± 0.03, Cd <= 0.025 (docs/PROGRESS.md, session 7; scripts/gated_sweep.py).
Witness m 0.085, p 0.30, t 0.12, alpha 9.0: interior of the passing region (camber below the
0.09 bound, thickness above the 0.0955 floor) and surrounded by passing grid points.
"""

import pytest

from swarm.briefs import NEAR_TARGET_FACTOR
from swarm.cad.build import build
from swarm.critic.numeric import in_target, stall_check_required, validate
from swarm.critic.screen import surrogate_screen
from swarm.critic.stall import measure_stall_margin
from swarm.run import HARD_SPEC
from swarm.solvers import neuralfoil, xfoil
from swarm.solvers.xfoil import xfoil_available
from swarm.state import WingParams

WITNESS = WingParams(main_camber=0.085, main_camber_pos=0.30, main_thickness=0.12, alpha_deg=9.0)


def test_hard_spec_is_the_gated_target():
    assert (HARD_SPEC.target_cl, HARD_SPEC.cl_tol, HARD_SPEC.cd_max) == (-1.83, 0.03, 0.025)
    assert WITNESS.main_camber < WingParams.bounds()["main_camber"][1]  # interior, not on the camber bound


def test_witness_passes_the_neuralfoil_screen_and_is_promotable():
    sc = surrogate_screen(WITNESS, HARD_SPEC)
    assert sc.ok and sc.dcl_dalpha >= sc.stall_threshold and not sc.sep_warning
    r = neuralfoil.evaluate(WITNESS, HARD_SPEC)
    assert abs(r.cl - HARD_SPEC.target_cl) <= NEAR_TARGET_FACTOR * HARD_SPEC.cl_tol and r.cd <= HARD_SPEC.cd_max
    assert validate(r, WITNESS, HARD_SPEC, [], screen=sc).status == "PASS"  # a NeuralFoil-tier pass


@pytest.mark.xfoil
@pytest.mark.skipif(not xfoil_available(), reason="xfoil binary not installed")
def test_witness_passes_the_full_xfoil_gate(tmp_path):
    geo = build(WITNESS, HARD_SPEC, tmp_path)
    assert not geo.violations
    r = None
    for lvl in range(xfoil.MAX_LEVEL + 1):  # cold, through the ladder, as the pipeline solves it
        r = xfoil.evaluate(WITNESS, HARD_SPEC, geo.coords_path, tmp_path, lvl)
        if r.status == "converged":
            break
    assert r.status == "converged" and in_target(r, HARD_SPEC) and r.bl.te_separation_xc is None
    rep = validate(r, WITNESS, HARD_SPEC, [])
    assert stall_check_required(r, rep)
    sm = measure_stall_margin(
        r,
        WITNESS.alpha_deg,
        lambda a, lvl: xfoil.evaluate(WITNESS, HARD_SPEC, geo.coords_path, tmp_path, lvl, alpha_deg=a),
    )
    assert sm.ok and sm.dcl_dalpha >= sm.threshold and all(x is None for x in sm.te_separation_xc)
    final = validate(r, WITNESS, HARD_SPEC, [], stall=sm)
    assert final.status == "PASS" and final.terminal
