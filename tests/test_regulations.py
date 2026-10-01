"""FS2026 checks run on outlines scaled to mm and placed at the mount height."""

import pytest

from swarm.cad.build import build, placed_mm
from swarm.cad.regulations import check_regulations, le_radius_mm, min_thickness_for_le_radius
from swarm.state import PLACEHOLDER_CAR, WingParams

LEGAL = WingParams(main_camber=0.05, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=10.0)


def test_known_legal_design_passes():
    els = placed_mm(LEGAL, PLACEHOLDER_CAR)
    pts = els["main"]
    assert 900 < pts[:, 1].min() and pts[:, 1].max() < 1100  # really placed in mm at ~950 mm
    assert check_regulations(els, LEGAL, PLACEHOLDER_CAR) == []


def test_known_illegal_design_too_high():
    # Same section, but mounted so the raised TE (alpha 14°) pokes above 1100 mm.
    car = PLACEHOLDER_CAR.model_copy(update={"wing_mount_z": 1050.0})
    p = LEGAL.model_copy(update={"alpha_deg": 14.0})
    top = placed_mm(p, car)["main"][:, 1].max()
    assert top == pytest.approx(1050 + 300 * 0.2419, abs=10)
    v = check_regulations(placed_mm(p, car), p, car)
    assert len(v) == 1 and v[0].startswith("T8.2.1")


def test_illegal_le_radius_names_rule_and_fix():
    thin = LEGAL.model_copy(update={"main_thickness": 0.085})
    assert le_radius_mm(0.085, 300) == pytest.approx(2.39, abs=0.01)
    v = check_regulations(placed_mm(thin, PLACEHOLDER_CAR), thin, PLACEHOLDER_CAR)
    assert len(v) == 1 and v[0].startswith("T2.4.1") and "at least 0.0953" in v[0]
    assert min_thickness_for_le_radius(300) == pytest.approx(0.0953, abs=1e-4)


def test_overhang_and_forward_height():
    far = PLACEHOLDER_CAR.model_copy(update={"wing_mount_x": 1850.0})
    v = check_regulations(placed_mm(LEGAL, far), LEGAL, far)
    assert any(x.startswith("T8.2.3") for x in v)
    fwd = PLACEHOLDER_CAR.model_copy(update={"head_restraint_x": 2500.0})
    v = check_regulations(placed_mm(LEGAL, fwd), LEGAL, fwd)
    assert any("head-restraint" in x for x in v)


def test_build_reports_regulation_violation(spec, tmp_path):
    thin = LEGAL.model_copy(update={"main_thickness": 0.085})
    geo = build(thin, spec, tmp_path)
    assert not geo.checks["regulations"] and geo.violations[0].startswith("T2.4.1")


def test_te_thickness_rule_measured_in_mm():
    import numpy as np

    from swarm.cad.build import naca4

    els = placed_mm(LEGAL, PLACEHOLDER_CAR)
    assert np.hypot(*(els["main"][0] - els["main"][-1])) > 2.0  # default blunt TE ≈ 2.9 mm
    sharp = naca4(0.05, 0.4, 0.12, te_thick=0.0) * 300 + np.array([1760, 950])
    v = check_regulations({"main": sharp}, LEGAL, PLACEHOLDER_CAR)
    assert any("TE thickness" in x for x in v)
