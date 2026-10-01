import numpy as np
import pytest

from swarm.cad.build import DEFAULT_TE_THICK, build, main_section, naca4, placed, placed_mm, validate_section
from swarm.state import WingParams


def test_naca4_shape_and_ordering():
    xy = naca4(0.04, 0.4, 0.12)
    assert xy.shape == (321, 2)
    assert xy[0, 0] == pytest.approx(1.0, abs=2e-3) and xy[-1, 0] == pytest.approx(1.0, abs=2e-3)  # TE … TE
    assert xy[160, 0] == pytest.approx(0.0, abs=1e-9)  # LE in the middle
    assert xy[0, 1] > xy[-1, 1]  # upper surface first
    te = np.hypot(*(xy[0] - xy[-1]))
    # NACA's own TE gap (0.021·t) plus the added blunt-TE thickness
    assert te == pytest.approx(DEFAULT_TE_THICK + 0.021 * 0.12, rel=0.05)


def test_naca4_symmetric_thickness():
    xy = naca4(0.0, 0.4, 0.12, te_thick=0.0)
    n = 161
    up, lo = xy[:n][::-1], xy[n - 1 :]
    assert np.allclose(up[:, 1], -lo[:, 1])
    assert 2 * up[:, 1].max() == pytest.approx(0.12, rel=0.01)


def test_validate_section_passes_and_detects_crossing():
    checks, v, te = validate_section(naca4(0.04, 0.4, 0.12))
    assert all(checks.values()) and v == [] and te > 0
    bowtie = np.array([[1, 0.05], [0, 0], [1, -0.05], [0.0, 0.0001], [1.0, 0.0499]])
    checks, v, _ = validate_section(bowtie)
    assert not checks["no_self_intersection"]


def test_validate_section_te_floor():
    checks, v, _ = validate_section(naca4(0.04, 0.4, 0.08, te_thick=0.0))
    assert not checks["te_above_mesh_floor"] and any("mesh floor" in m for m in v)


def test_placed_is_inverted_with_te_up():
    p = WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=10)
    xy = placed(p)
    te = xy[0]
    assert te[1] > 0.15  # TE rotated up
    # inverted camber: the mean line bulges downward (suction side faces the ground)
    up = main_section(p)
    assert up[80, 1] > 0 and placed(p.model_copy(update={"alpha_deg": 0.0}))[80, 1] < 0


def test_placed_mm_scales_and_positions(spec):
    p = WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=0.0)
    main = placed_mm(p, spec.car)["main"]
    car = spec.car
    assert main[:, 0].min() == pytest.approx(car.wing_mount_x, abs=0.5)  # LE at the mount point
    assert main[:, 0].max() - main[:, 0].min() == pytest.approx(car.chord_mm, abs=0.5)
    assert abs(main[:, 1].mean() - car.wing_mount_z) < 20


def test_build_writes_coords_and_flags_flap_on_single_element(spec, tmp_path):
    p = WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=6)
    geo = build(p, spec, tmp_path)
    assert geo.violations == [] and geo.checks["regulations"]
    lines = open(geo.coords_path).read().splitlines()
    assert lines[0] == f"aeroswarm-{p.cid}" and len(lines) == 322
    p2 = p.model_copy(update={"flap_chord_ratio": 0.3})
    assert any("wing_1el" in v for v in build(p2, spec, tmp_path).violations)
