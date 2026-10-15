"""T2 OpenFOAM tier (milestone 5, part 1), offline: O-grid validity, polyMesh bookkeeping, case files, forces from
synthetic fields, the divergence monitor and the log parsers on recorded OpenFOAM v1912 logs. Runs that need
OpenFOAM itself are in scripts/of_validate.py (results in docs/OPENFOAM.md)."""

import itertools
import math
import re
from pathlib import Path

import numpy as np
import pytest

from swarm.cad.build import main_section, naca4
from swarm.solvers.openfoam import exec as foam
from swarm.solvers.openfoam import forces
from swarm.solvers.openfoam.case import SolverOverrides, freestream, write_case
from swarm.solvers.openfoam.mesh import MeshSpec, load_wall, o_grid, quality, surface_loop, write_polymesh
from swarm.solvers.openfoam.monitor import Monitor, iteration_of
from swarm.solvers.openfoam.solver import (
    DEFAULT_MESH,
    drop_orders,
    evaluate,
    parse_checkmesh,
    rel_std_window,
    residual_history,
)
from swarm.state import WingParams

FIX = Path(__file__).parent / "fixtures" / "openfoam"
SMALL = MeshSpec(n_surface=60, n_base=4, first_cell=1e-3, growth=1.3, max_step=0.5, farfield=3.0, span=0.1)


def _read_list(path: Path) -> list[str]:
    text = path.read_text()
    body = text[text.index("(", text.index("}")) + 1 : text.rindex(")")]
    return [x for x in body.split("\n") if x.strip()]


def test_surface_loop_is_counter_clockwise_and_closed_through_the_base():
    loop = surface_loop(
        main_section(WingParams(main_camber=0.08, main_camber_pos=0.35, main_thickness=0.135, alpha_deg=5)),
        DEFAULT_MESH,
    )
    x, y = loop[:, 0], loop[:, 1]
    assert 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) > 0
    assert len(loop) == DEFAULT_MESH.n_surface + DEFAULT_MESH.n_base
    g = np.array([loop, loop * 1.01])  # any second layer: the base flags depend on the surface only
    from swarm.solvers.openfoam.mesh import wall_geometry

    assert wall_geometry(g)["base"].sum() == DEFAULT_MESH.n_base  # the blunt base is part of the wall


@pytest.mark.parametrize(
    "m,p,t", list(itertools.product([0.0, 0.04, 0.09], [0.2, 0.4, 0.6], [0.123, 0.18]))
)  # every FSAE-legal corner of the camber / position / thickness box
def test_o_grid_never_folds_and_stays_orthogonal_on_legal_sections(m, p, t):
    from swarm.solvers.openfoam.mesh import _interior_point

    sec = main_section(WingParams(main_camber=m, main_camber_pos=p, main_thickness=t, alpha_deg=5))
    g = o_grid(sec, DEFAULT_MESH)
    q = quality(g)
    assert q["folded"] == 0 and q["max_non_ortho"] < 60
    r = np.linalg.norm(g[-1] - _interior_point(surface_loop(sec, DEFAULT_MESH)), axis=1)
    assert r.min() >= DEFAULT_MESH.farfield and r.max() / r.min() < 1.0001  # far field is a circle


def test_polymesh_bookkeeping(tmp_path):
    g = o_grid(naca4(0.0, 0.4, 0.12, n=61), SMALL)
    info = write_polymesh(g, tmp_path, SMALL.span)
    d = tmp_path / "constant" / "polyMesh"
    faces, owner, neigh = (_read_list(d / f) for f in ("faces", "owner", "neighbour"))
    assert len(faces) == len(owner) == info["faces"]
    ncells = info["cells"]
    assert ncells == info["n_around"] * info["n_layers"]
    count = np.bincount([int(o) for o in owner] + [int(n) for n in neigh], minlength=ncells)
    assert np.all(count == 6)  # every hexahedron has six faces
    own_int = [int(o) for o in owner[: len(neigh)]]
    assert all(o < int(n) for o, n in zip(own_int, neigh, strict=True))  # upper-triangular order
    assert own_int == sorted(own_int)
    b = (d / "boundary").read_text()
    for name, n in (("airfoil", info["n_around"]), ("farfield", info["n_around"]), ("frontAndBack", 2 * ncells)):
        assert re.search(rf"{name}\s*\{{\s*type \w+;\s*nFaces {n};", b)
    assert f"nCells:{ncells}" in (d / "owner").read_text()


def test_wall_normals_point_into_the_body(tmp_path):
    g = o_grid(naca4(0.04, 0.4, 0.12, n=61), SMALL)
    write_polymesh(g, tmp_path, SMALL.span)
    w = load_wall(tmp_path)
    from matplotlib.path import Path as Poly

    inside = Poly(g[0]).contains_points(w["centre"] + 1e-4 * w["n_in"])
    assert inside.mean() > 0.95
    assert np.all(w["dist"] > 0) and np.allclose(np.linalg.norm(w["t"], axis=1), 1)


def _field(path: Path, values: np.ndarray, cls: str) -> None:
    if values.ndim == 1:
        body = "\n".join(f"{v:.10g}" for v in values)
        kind = "scalar"
    else:
        body = "\n".join(f"({a:.10g} {b:.10g} {c:.10g})" for a, b, c in values)
        kind = "vector"
    path.write_text(
        f"FoamFile {{ class {cls}; object {path.name}; }}\ndimensions [0 0 0 0 0 0 0];\n"
        f"internalField nonuniform List<{kind}>\n{len(values)}\n(\n{body}\n)\n;\nboundaryField {{}}\n"
    )


def _synthetic_case(tmp_path, p_of_xy, u=(0.0, 0.0)):
    g = o_grid(naca4(0.0, 0.4, 0.12, n=101), SMALL)
    info = write_polymesh(g, tmp_path, SMALL.span)
    write_case(tmp_path, 0.0, 1e6, SMALL.span, SolverOverrides())
    a, b = g[:-1], np.roll(g[:-1], -1, axis=1)
    c, d = np.roll(g[1:], -1, axis=1), g[1:]
    cent = (0.25 * (a + b + c + d)).reshape(-1, 2)
    td = tmp_path / "100"
    td.mkdir()
    _field(td / "p", p_of_xy(cent[:, 0], cent[:, 1]), "volScalarField")
    _field(td / "U", np.tile([u[0], u[1], 0.0], (info["cells"], 1)), "volVectorField")
    return g


def test_forces_integrate_a_known_pressure_field_exactly(tmp_path):
    # p = -y: the pressure force on the body is (0, A * span), A the section area (divergence theorem)
    g = _synthetic_case(tmp_path, lambda x, y: -y)
    c = forces.coefficients(tmp_path, tmp_path / "100", 0.0, 1e6, SMALL.span)
    x, y = g[0][:, 0], g[0][:, 1]
    area = 0.5 * abs(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    assert c["cl"] == pytest.approx(area * SMALL.span / (0.5 * SMALL.span), rel=0.03)
    assert abs(c["cd"]) < 1e-3
    assert forces.span_of(tmp_path) == SMALL.span


def test_uniform_pressure_gives_no_force_and_the_surface_splits_at_the_leading_edge(tmp_path):
    _synthetic_case(tmp_path, lambda x, y: np.full_like(x, 0.7))
    c = forces.coefficients(tmp_path, tmp_path / "100", 0.0, 1e6, SMALL.span)
    assert abs(c["cl"]) < 1e-9 and abs(c["cd"]) < 1e-9
    s = forces.surface(c, 1.0)
    for side in ("suction", "pressure"):
        x = s[side]["x"]
        assert np.all(np.diff(x) >= 0) and x.min() < 0.02 and x.max() > 0.95
    assert np.allclose(s["suction"]["cp"], 1.4)


def test_read_internal_uniform_and_nonuniform(tmp_path):
    f = tmp_path / "k"
    f.write_text("FoamFile {}\ninternalField uniform 2.5;\n")
    assert np.all(forces.read_internal(f, 3) == 2.5)
    _field(f, np.array([[1.0, 2.0, 0.0], [3.0, -4.5e-3, 0.0]]), "volVectorField")
    assert forces.read_internal(f, 2).tolist() == [[1.0, 2.0, 0.0], [3.0, -4.5e-3, 0.0]]


def test_case_files(tmp_path):
    write_case(tmp_path, 8.75, 3e5, 0.1, SolverOverrides(relax_p=0.2, first_order=True))
    ux, uy = freestream(8.75)
    assert math.isclose(math.hypot(ux, uy), 1.0)
    u0 = (tmp_path / "0" / "U").read_text()
    assert f"({ux:.10f} {uy:.10f} 0)" in u0 and "freestreamVelocity" in u0
    assert "nu 3.333333333e-06;" in (tmp_path / "constant" / "transportProperties").read_text()
    fs = (tmp_path / "system" / "fvSolution").read_text()
    assert "p 0.2;" in fs and "PCG" in fs and "GAMG" not in fs  # GAMG diverges on this mesh in v1912
    sch = (tmp_path / "system" / "fvSchemes").read_text()
    assert "div(phi,U) bounded Gauss upwind;" in sch and "div(phi,omega) bounded Gauss upwind;" in sch
    cd = (tmp_path / "system" / "controlDict").read_text()
    assert "functions" not in cd and "// span 0.1" in cd  # function objects abort in the v1912 package


def test_overrides_are_bounded():
    with pytest.raises(ValueError):
        SolverOverrides(relax_U=0.95)
    with pytest.raises(ValueError):
        SolverOverrides(max_iter=50)


def test_monitor_kills_a_diverging_run_before_the_crash_and_spares_a_healthy_one():
    m = Monitor()
    sig = next(s for line in (FIX / "log.simpleFoam.fpe").read_text().splitlines() if (s := m.feed(line)))
    assert sig.startswith("solver_blowup@it") and iteration_of(sig) <= 48
    assert Monitor().post_mortem(FIX / "log.simpleFoam.fpe") == "FPE@it48"
    m = Monitor()
    assert not any(m.feed(line) for line in (FIX / "log.simpleFoam.ok").read_text().splitlines())
    assert Monitor().post_mortem(FIX / "log.simpleFoam.ok") is None


def test_monitor_signatures():
    m = Monitor(window=3, blowup_after=2)
    assert m.feed("Time = 3") is None
    assert m.feed("smoothSolver:  Solving for Ux, Initial residual = 2.0, Final residual = 0.1, No Iterations 3") == (
        "residual_blowup@it3:Ux"
    )
    m = Monitor()
    assert m.feed("Solving for p, Initial residual = nan, Final residual = nan, No Iterations 0").startswith("FPE")
    m = Monitor(max_bounding=2)
    assert [m.feed("bounding omega, min: -1 max: 3 average: 1") for _ in range(3)][-1] == "persistent_bounding:omega"
    assert Monitor().feed("trapFpe: Floating point exception trapping enabled (FOAM_SIGFPE).") is None


def test_log_parsers():
    h = residual_history(FIX / "log.simpleFoam.ok")
    assert {"p", "Ux", "Uy", "k", "omega"} <= set(h) and len(h["p"]) >= 5
    assert drop_orders(h["p"]) > 5  # the fixture is the start and the end of a converged run
    assert drop_orders([1.0, 0.5, 1e-4]) == pytest.approx(4.0)
    assert drop_orders([1.0]) is None and drop_orders([float("nan"), 1e-3]) is None
    ok = parse_checkmesh(FIX / "log.checkMesh.ok")
    assert ok["ok"] and ok["cells"] > 1000 and ok["max_non_ortho"] < 70 and ok["failed_checks"] == 0
    bad = parse_checkmesh(FIX / "log.checkMesh.failed")
    assert not bad["ok"] and bad["failed_checks"] >= 1 and bad["max_non_ortho"] > 70


def test_coefficient_window():
    hist = [(it, 1.0 + (0.01 if it % 100 else 0.0), 0.02) for it in range(0, 3001, 50)]
    w = rel_std_window(hist)
    assert set(w) == {"cl", "cd"} and w["cd"] == 0.0 and 0 < w["cl"] < 0.01
    assert rel_std_window(hist[:2]) == {}


def test_only_allowed_applications_run(tmp_path):
    with pytest.raises(PermissionError):
        foam.run("rm", tmp_path)
    with pytest.raises(PermissionError):
        foam.run("bash", tmp_path)


def test_evaluate_without_openfoam_reports_it(spec, tmp_path, monkeypatch):
    monkeypatch.setattr(foam, "available", lambda: False)
    r = evaluate(WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=4.0), spec, tmp_path)
    assert r.fidelity == "of2d" and r.status == "mesh_failed" and r.failure_signature == "openfoam_missing"
