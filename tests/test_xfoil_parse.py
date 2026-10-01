"""XFoil output parsing and separation classification, on recorded output (no binary)."""

import numpy as np
import pytest
from conftest import FIXTURES

from swarm.solvers.xfoil import (
    alpha_schedule,
    build_script,
    classify_separation,
    parse_dump,
    parse_polar,
    summarize_bl,
)


def test_parse_polar_fixture():
    rows = parse_polar((FIXTURES / "xfoil_polar_sep13.txt").read_text())
    assert len(rows) == 1
    r = rows[0]
    assert r["alpha"] == 13.0 and r["cl"] == pytest.approx(1.6951) and r["cd"] == pytest.approx(0.03831)
    assert r["top_xtr"] == pytest.approx(0.0307)


def test_parse_polar_tolerates_garbage():
    assert parse_polar("") == []
    assert parse_polar("no header here\n1 2 3") == []
    txt = "header\n ------ ----\n  4.000 0.9 0.008 0.001 -0.1 0.4 1.0\n junk line\n"
    assert parse_polar(txt)[0]["cl"] == 0.9


def test_parse_dump_splits_surfaces_and_drops_wake():
    d = parse_dump((FIXTURES / "xfoil_dump_att4.txt").read_text())
    assert d is not None
    for s in (d.upper, d.lower):
        assert s.x[0] == pytest.approx(0.0, abs=0.01) and s.x[-1] == pytest.approx(1.0, abs=1e-3)
        assert np.all(np.diff(s.x) >= -1e-6)  # LE → TE, monotone
    assert len(d.upper.x) + len(d.lower.x) == 160 + 1  # 160 panel nodes; LE row in both


def test_classify_te_separation_vs_bubble():
    x = np.linspace(0, 1, 21)
    cf = np.full(21, 0.003)
    cf[3:5] = -0.001  # reattaches → bubble
    cf[16:] = -0.0005  # persists to the TE → separation
    te, bubbles = classify_separation(x, cf)
    assert te == pytest.approx(x[16])
    assert bubbles == [(pytest.approx(x[3]), pytest.approx(x[5]))]


def test_bubble_only_is_not_te_separation():
    x = np.linspace(0, 1, 21)
    cf = np.full(21, 0.003)
    cf[8:12] = -0.001
    te, bubbles = classify_separation(x, cf)
    assert te is None and len(bubbles) == 1


def test_single_station_te_blip_is_not_separation():
    x = np.linspace(0, 1, 21)
    cf = np.full(21, 0.003)
    cf[-1] = -1e-5
    te, bubbles = classify_separation(x, cf)
    assert te is None and bubbles == [(1.0, 1.0)]


def test_recorded_stall_case_has_te_separation_and_le_bubble():
    d = parse_dump((FIXTURES / "xfoil_dump_sep13.txt").read_text())
    bl = summarize_bl(d, upright_cl=1.6951, transition={"top_xtr": 0.0307})
    assert bl.suction_side == "upper" and bl.source == "xfoil_cf"
    assert bl.te_separation_xc == pytest.approx(0.78, abs=0.02)
    assert len(bl.bubbles) == 1 and bl.bubbles[0][1] < 0.05  # LE laminar bubble, reattached


def test_recorded_attached_case():
    d = parse_dump((FIXTURES / "xfoil_dump_att4.txt").read_text())
    bl = summarize_bl(d, upright_cl=0.7, transition={})
    assert bl.te_separation_xc is None and bl.bubbles == []


def test_script_turns_graphics_off_first():
    s = build_script("coords.dat", 8.3e5, [0.0, 0.5, 1.0], 100, 160, ncrit=9).splitlines()
    assert s[:3] == ["PLOP", "G", ""]
    assert "VISC 830000" in s and "N 9" in s and "N 160" in s
    assert s[-1] == "QUIT"


def test_alpha_continuation():
    assert alpha_schedule(6.0, False) == [6.0]
    seq = alpha_schedule(2.2, True)
    assert seq == [0.0, 0.5, 1.0, 1.5, 2.0, 2.2]
    assert alpha_schedule(-1.2, True) == [0.0, -0.5, -1.0, -1.2]
    assert alpha_schedule(0.3, True) == [0.3]
