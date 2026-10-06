"""Rulebook checks run on outlines scaled to mm and placed at the mount height.

FSAE 2027 v1.0 (the default; docs/FSAE_Rules_2027_V1.pdf T.7, V.1.4) and FS 2026 v1.1.
"""

import numpy as np
import pytest

from swarm.cad.build import build, naca4, placed_mm
from swarm.cad.regulations import RULEBOOKS, check_regulations, le_radius_mm, min_thickness_for_le_radius
from swarm.state import PLACEHOLDER_CAR, DesignSpec, WingParams

LEGAL = WingParams(main_camber=0.05, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=10.0)
FS = "FS2026_v1.1"


def test_fsae_2027_numbers_match_the_rulebook():
    rb = RULEBOOKS["FSAE2027_v1.0"]
    assert (rb.rear_max_height.value, rb.rear_max_height.rule) == (1200, "T.7.7.1a")
    assert (rb.forward_max_height.value, rb.forward_max_height.rule) == (500, "T.7.7.1b")
    assert (rb.max_behind_rear_tire.value, rb.max_behind_rear_tire.rule) == (250, "T.7.5b")
    assert (rb.le_radius_min.value, rb.le_radius_min.rule) == (5.0, "T.7.1.4")
    assert rb.min_ground_clearance.rule == "V.1.4.1" and rb.heights_inclusive  # "no higher than"
    assert DesignSpec(component="wing_1el", target_cl=-1.5, cl_tol=0.03, cd_max=0.02, speed_mps=40).rulebook == (
        "FSAE2027_v1.0"
    )


def test_known_legal_design_passes_both_rulebooks():
    els = placed_mm(LEGAL, PLACEHOLDER_CAR)
    pts = els["main"]
    assert 900 < pts[:, 1].min() and pts[:, 1].max() < 1100  # really placed in mm at ~950 mm
    assert check_regulations(els, LEGAL, PLACEHOLDER_CAR) == []
    assert check_regulations(els, LEGAL, PLACEHOLDER_CAR, FS) == []


def test_fsae_le_radius_needs_5_mm():
    assert min_thickness_for_le_radius(300) == pytest.approx(0.1230, abs=1e-4)  # 5 mm on 300 mm
    assert min_thickness_for_le_radius(300, FS) == pytest.approx(0.0953, abs=1e-4)  # 3 mm
    p = LEGAL.model_copy(update={"main_thickness": 0.12})  # 4.76 mm: FS-legal, FSAE-illegal
    assert le_radius_mm(0.12, 300) == pytest.approx(4.76, abs=0.01)
    v = check_regulations(placed_mm(p, PLACEHOLDER_CAR), p, PLACEHOLDER_CAR)
    assert len(v) == 1 and v[0].startswith("T.7.1.4") and "at least 0.1230" in v[0]
    assert check_regulations(placed_mm(p, PLACEHOLDER_CAR), p, PLACEHOLDER_CAR, FS) == []


def test_height_limits_differ_1200_vs_1100():
    # Same section, mounted so the raised TE (alpha 14°) reaches ~1123 mm: FS-illegal, FSAE-legal.
    car = PLACEHOLDER_CAR.model_copy(update={"wing_mount_z": 1050.0})
    p = LEGAL.model_copy(update={"alpha_deg": 14.0})
    els = placed_mm(p, car)
    assert 1100 < els["main"][:, 1].max() < 1200
    v = check_regulations(els, p, car, FS)
    assert len(v) == 1 and v[0].startswith("T8.2.1")
    assert check_regulations(els, p, car) == []
    high = car.model_copy(update={"wing_mount_z": 1150.0})
    v = check_regulations(placed_mm(p, high), p, high)
    assert len(v) == 1 and v[0].startswith("T.7.7.1a")


def test_overhang_and_forward_height():
    far = PLACEHOLDER_CAR.model_copy(update={"wing_mount_x": 1850.0})
    assert any(x.startswith("T.7.5b") for x in check_regulations(placed_mm(LEGAL, far), LEGAL, far))
    assert any(x.startswith("T8.2.3") for x in check_regulations(placed_mm(LEGAL, far), LEGAL, far, FS))
    fwd = PLACEHOLDER_CAR.model_copy(update={"head_restraint_x": 2500.0})
    v = check_regulations(placed_mm(LEGAL, fwd), LEGAL, fwd)
    assert any(x.startswith("T.7.7.1b") and "head-restraint" in x for x in v)


def test_ground_contact_and_clearance():
    low = PLACEHOLDER_CAR.model_copy(update={"wing_mount_z": 0.0})  # lowest point ~ -20 mm: in the ground
    v = check_regulations(placed_mm(LEGAL, low), LEGAL, low)
    assert any(x.startswith("V.1.4.1") for x in v)
    near = PLACEHOLDER_CAR.model_copy(update={"wing_mount_z": 40.0})  # ~20 mm: FS needs 30, FSAE no number
    els = placed_mm(LEGAL, near)
    assert 0 < els["main"][:, 1].min() < 30
    assert not any(x.startswith("V.1.4.1") for x in check_regulations(els, LEGAL, near))
    assert any(x.startswith("T2.2.1") for x in check_regulations(els, LEGAL, near, FS))


def test_build_reports_regulation_violation(spec, tmp_path):
    thin = LEGAL.model_copy(update={"main_thickness": 0.11})
    geo = build(thin, spec, tmp_path)
    assert not geo.checks["regulations"] and geo.violations[0].startswith("T.7.1.4")
    fs_spec = spec.model_copy(update={"rulebook": FS})
    assert build(thin, fs_spec, tmp_path).violations == []
    assert build(thin, spec.model_copy(update={"rulebook": "none"}), tmp_path).violations == []


def test_te_must_not_be_sharp_measured_in_mm():
    els = placed_mm(LEGAL, PLACEHOLDER_CAR)
    assert np.hypot(*(els["main"][0] - els["main"][-1])) > 2.0  # default blunt TE ≈ 2.9 mm
    sharp = naca4(0.05, 0.4, 0.13, te_thick=0.0) * 300 + np.array([1760, 950])
    v = check_regulations({"main": sharp}, LEGAL, PLACEHOLDER_CAR)
    assert any(x.startswith("T.7.1.5") and "TE thickness" in x for x in v)
