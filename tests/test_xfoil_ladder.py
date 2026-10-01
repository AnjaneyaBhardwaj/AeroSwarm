"""XFoil recovery ladder with the subprocess mocked (recorded output, no binary)."""

import subprocess

from conftest import FIXTURES

from swarm.cad.build import build
from swarm.solvers import xfoil
from swarm.state import WingParams

P = WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=13.0)


def fake_exec(converge_at: set[int]):
    seen = []

    def _exec(argv, script, cwd, timeout):
        level = next(
            lvl
            for lvl, c in xfoil.LEVELS.items()
            if f"N {c['npanel']}" in script
            and f"ITER {c['n_iter']}" in script
            and (("ALFA 0.000" in script) == c["continuation"])
        )
        seen.append((level, script))
        polar = (FIXTURES / "xfoil_polar_sep13.txt").read_text()
        if level not in converge_at:  # header only: target alpha missing
            polar = "\n".join(polar.splitlines()[:-1]) + "\n"
        (cwd / xfoil.POLAR).write_text(polar)
        (cwd / xfoil.DUMP).write_text((FIXTURES / "xfoil_dump_sep13.txt").read_text())
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    return _exec, seen


def test_levels_and_results(spec, tmp_path, monkeypatch):
    monkeypatch.setenv("XFOIL_BIN", "/bin/true")
    ex, seen = fake_exec({2})
    monkeypatch.setattr(xfoil, "_exec", ex)
    geo = build(P, spec, tmp_path)
    results = [xfoil.evaluate(P, spec, geo.coords_path, tmp_path, lvl) for lvl in (0, 1, 2)]
    assert [r.status for r in results] == ["not_converged", "not_converged", "converged"]
    assert results[0].failure_signature == "not_converged@L0"
    r = results[2]
    assert r.solver_level == 2 and r.cl == -1.6951 and r.cd == 0.03831  # negated: race-car convention
    assert r.bl.te_separation_xc is not None
    # L2 is alpha continuation; every script starts with graphics off
    assert "ALFA 0.000" in seen[2][1] and "ALFA 0.000" not in seen[0][1]
    assert all(s.startswith("PLOP\nG\n\n") for _, s in seen)


def test_timeout(spec, tmp_path, monkeypatch):
    monkeypatch.setenv("XFOIL_BIN", "/bin/true")

    def _exec(argv, script, cwd, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)

    monkeypatch.setattr(xfoil, "_exec", _exec)
    geo = build(P, spec, tmp_path)
    r = xfoil.evaluate(P, spec, geo.coords_path, tmp_path, 0)
    assert r.status == "timeout" and r.failure_signature == "timeout@L0"


def test_missing_binary(spec, tmp_path, monkeypatch):
    monkeypatch.setenv("XFOIL_BIN", "")
    monkeypatch.setenv("PATH", "/nonexistent")
    geo = build(P, spec, tmp_path)
    r = xfoil.evaluate(P, spec, geo.coords_path, tmp_path, 0)
    assert r.status == "not_converged" and r.failure_signature == "xfoil_missing"


def test_next_level_never_repeats():
    assert xfoil.next_level([]) == 0
    assert xfoil.next_level([0, 1]) == 2
    assert xfoil.next_level([0, 2]) == 1
    assert xfoil.next_level([0, 1, 2, 3]) is None
