"""Proves the real XFoil binary runs headless with graphics off in this container.

Skipped when no xfoil binary is installed (run `make xfoil`).
"""

import os
import subprocess

import pytest

from swarm.cad.build import build
from swarm.solvers import xfoil
from swarm.state import WingParams

pytestmark = [pytest.mark.xfoil, pytest.mark.skipif(not xfoil.xfoil_available(), reason="xfoil binary not installed")]

P = WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=4.0)


def _raw(script: str, cwd, display: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DISPLAY": display}  # an X display that does not exist
    return subprocess.run(
        [xfoil.xfoil_bin()], input=script, text=True, capture_output=True, timeout=30, cwd=cwd, env=env
    )


def test_graphics_off_runs_with_no_x_server(spec, tmp_path):
    geo = build(P, spec, tmp_path)
    (tmp_path / "coords.dat").write_text(open(geo.coords_path).read())
    script = xfoil.build_script("coords.dat", spec.reynolds, [P.alpha_deg], 100, 160, spec.ncrit)
    proc = _raw(script, tmp_path, display=":99")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-2000:]
    assert "Cannot open display" not in out and "SIGFPE" not in out
    assert "Graphics-enable flag:        F" in out.replace("G raphics", "Graphics")
    rows = xfoil.parse_polar((tmp_path / xfoil.POLAR).read_text())
    assert rows and rows[-1]["alpha"] == pytest.approx(4.0)
    assert (tmp_path / xfoil.DUMP).exists() and (tmp_path / xfoil.CPWR).exists()


def test_negative_control_graphics_on_needs_a_display(tmp_path):
    """Without `PLOP G` the same binary tries to open X and aborts: the test above is meaningful."""
    script = "NACA 4412\nOPER\nALFA 4\n\nQUIT\n"
    proc = _raw(script, tmp_path, display=":99")
    assert "Cannot open display" in proc.stdout + proc.stderr


def test_wrapper_evaluate_end_to_end(spec, tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")  # the wrapper must strip it anyway
    geo = build(P, spec, tmp_path)
    r = xfoil.evaluate(P, spec, geo.coords_path, tmp_path, 0)
    assert r.status == "converged" and r.fidelity == "xfoil"
    assert -1.0 < r.cl < -0.5 and 0.005 < r.cd < 0.012  # NACA 2412-ish at 4°, race-car sign
    assert r.bl is not None and r.bl.source == "xfoil_cf"
