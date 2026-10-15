"""OpenFOAM recovery ladder and CFD agent (milestone 5 part 2), offline: classification, levels as bounded changes,
the agent's coercion (no repeats, bounded), the mock's policy, the ladder loop with a fake solver, the two-stage
L2 run, and the transition-model case files."""

import json
from pathlib import Path

import pytest

from swarm.agents import cfd
from swarm.briefs import cfd_brief
from swarm.llm.client import ScriptedClient, TraceLogger
from swarm.llm.mock import MockClient
from swarm.solvers.openfoam import recovery, solver
from swarm.solvers.openfoam.case import SolverOverrides, retheta_t_freestream, write_case
from swarm.solvers.openfoam.exec import RunOutcome
from swarm.solvers.openfoam.mesh import MeshSpec
from swarm.state import CFDResult, RecoveryAction, WingParams

P = WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=4.0)


@pytest.mark.parametrize(
    "sig,status,cls",
    [
        ("solver_blowup@it46:Ux", "diverged", "mesh"),
        ("FPE@it12", "diverged", "mesh"),
        ("residual_growth@it100:Ux", "diverged", "numerics"),
        ("checkMesh:1_failed", "mesh_failed", "mesh"),
        ("persistent_bounding:omega", "diverged", "turbulence"),
        ("timeout@3600s", "timeout", "numerics"),
        (None, "diverged", "unknown"),
    ],
)
def test_classification(sig, status, cls):
    assert recovery.classify(sig, status) == cls


def test_default_level_follows_the_class_and_never_repeats():
    assert recovery.default_level("solver_blowup@it46:Ux", "diverged", []) == 4
    assert recovery.default_level("residual_growth@it100:Ux", "diverged", []) == 1
    assert recovery.default_level("residual_growth@it100:Ux", "diverged", [1]) == 2
    assert recovery.default_level("persistent_bounding:k", "diverged", []) == 3
    assert recovery.default_level("FPE@it3", "diverged", [1, 2, 3, 4, 5]) is None
    # after a checkMesh failure only re-meshing or dropping fidelity can change anything
    assert recovery.default_level("checkMesh:1_failed", "mesh_failed", []) == 4
    assert recovery.default_level("checkMesh:1_failed", "mesh_failed", [4]) == 5


def test_levels_are_bounded_changes_of_the_base_setup():
    base, mesh = SolverOverrides(), MeshSpec(first_cell=2e-5, farfield=100.0, max_step=4.0)
    ov, m = recovery.apply_level(1, base, mesh)
    assert (ov.relax_U, ov.relax_p, ov.relax_turb) == (0.5, 0.2, 0.5) and m == mesh
    assert recovery.apply_level(2, base, mesh)[0].first_order_iters == 300
    ov, _ = recovery.apply_level(3, base, mesh)
    assert ov.potential_init and ov.viscosity_ratio == 1.0
    ov, m = recovery.apply_level(4, base, mesh)
    assert ov == base and m.first_cell == 8e-5 and m.farfield == 50.0 and m.growth <= 1.10 and m.smoothing == 8 * 12
    with pytest.raises(ValueError):
        recovery.apply_level(5, base, mesh)


def test_agent_coerces_a_repeated_or_impossible_level():
    f = {"signature": "residual_growth@it100:Ux", "status": "diverged"}
    a, note = cfd.sanitize(RecoveryAction(level=1, rationale="lower relaxation"), f, [1])
    assert a.level == 2 and "already tried" in note and a.rationale.startswith("[coerced from L1")
    a, note = cfd.sanitize(RecoveryAction(level=3, rationale="x"), f, [1])
    assert a.level == 3 and note is None
    assert cfd.sanitize(RecoveryAction(level=2, rationale="x"), f, [1, 2, 3, 4, 5]) == (
        None,
        "L2 refused and no level left",
    )
    with pytest.raises(ValueError):
        RecoveryAction(level=6, rationale="x")
    mesh_fail = {"signature": "checkMesh:1_failed", "status": "mesh_failed"}
    a, note = cfd.sanitize(RecoveryAction(level=1, rationale="x"), mesh_fail, [4])
    assert a.level == 5 and "cannot change a mesh failure" in note


def test_agent_brief_and_llm_choice(spec):
    f = {"signature": "solver_blowup@it46:Ux", "status": "diverged", "cid": P.cid, "alpha": 4.0,
         "residual_tail": {"p": 0.4}, "mesh": {"ok": True, "max_aspect": 1500.0}}  # fmt: skip
    b = cfd_brief(spec, f, [4])
    assert b.facts["failure_class"] == "mesh" and b.facts["iteration"] == 46 and b.facts["untried"] == [1, 2, 3, 5]
    assert "RecoveryAction" in b.system and "solver_blowup@it46:Ux" in b.user and "| L4 |" in b.user
    llm = ScriptedClient([RecoveryAction(level=4, rationale="aspect ratio 1500 at the wall", evidence="it46")])
    a, note = cfd.choose(llm, spec, f, [4])  # the LLM repeats L4: coerced to the policy's next choice
    assert a.level == 1 and note.startswith("L4 already tried")
    mock = MockClient(TraceLogger(None))
    assert cfd.choose(mock, spec, f, [])[0].level == 4  # the mock follows the class preference


def _result(status, sig=None, level=0):
    return CFDResult(cid=P.cid, fidelity="of2d", status=status, failure_signature=sig, cl=None if sig else -1.0,
                     cd=None if sig else 0.02, solver_level=level)  # fmt: skip


def test_ladder_loop_recovers_and_records_every_attempt(spec, tmp_path, monkeypatch):
    seen = []

    def fake_evaluate(params, spec, run_dir, overrides, mesh, tag, model, timeout, coords=None):
        seen.append((tag, overrides.relax_U, mesh.first_cell))
        return _result("converged") if tag == "L4" else _result("diverged", "solver_blowup@it46:Ux")

    monkeypatch.setattr(solver, "evaluate", fake_evaluate)
    pick = []

    def choose(failure, tried):
        pick.append(list(tried))
        return cfd.fallback(failure, tried)

    r, attempts = solver.evaluate_with_recovery(P, spec, tmp_path, choose, mesh=MeshSpec(first_cell=2e-5))
    assert r.status == "converged" and r.solver_level == 4
    assert [a["level"] for a in attempts] == [0, 4] and pick == [[]]
    assert seen[1] == ("L4", 0.7, 8e-5)


def test_ladder_loop_ends_at_l5_or_when_exhausted(spec, tmp_path, monkeypatch):
    monkeypatch.setattr(solver, "evaluate", lambda *a, **k: _result("diverged", "residual_growth@it300:Ux"))
    r, attempts = solver.evaluate_with_recovery(P, spec, tmp_path, cfd.fallback)
    assert [a["level"] for a in attempts] == [0, 1, 2, 3, 4, 5] and attempts[-1]["unsimulatable"]
    assert r.status == "diverged"
    r, attempts = solver.evaluate_with_recovery(
        P, spec, tmp_path, lambda f, t: RecoveryAction(level=5, rationale="massive separation at every alpha")
    )
    assert [a["level"] for a in attempts] == [0, 5]


def test_l2_runs_a_first_order_stage_then_second_order(spec, tmp_path, monkeypatch):
    from swarm.solvers.openfoam import exec as foam

    calls = []
    monkeypatch.setattr(foam, "available", lambda: True)

    def fake_run(app, case, args=(), timeout=0, on_line=None, log_name=None):
        case = Path(case)
        log = case / (log_name or f"log.{app}")
        if app == "checkMesh":
            log.write_text(
                "    cells:            100\nMesh non-orthogonality Max: 10\nMax skewness = 0.5 OK.\nMesh OK.\n"
            )
        else:
            schemes = (case / "system" / "fvSchemes").read_text()
            calls.append((log.name, "div(phi,U) bounded Gauss upwind;" in schemes, "endTime 300;" in
                          (case / "system" / "controlDict").read_text()))  # fmt: skip
            log.write_text(
                "Time = 1\nsmoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.1, No Iterations 1\n"
            )
        return RunOutcome(0, None, str(log), 0.1)

    monkeypatch.setattr(foam, "run", fake_run)
    solver.evaluate(
        P,
        spec,
        tmp_path,
        SolverOverrides(first_order_iters=300),
        MeshSpec(n_surface=60, farfield=3.0, max_step=0.5, first_cell=1e-3, growth=1.3),
    )
    assert calls == [("log.simpleFoam.stage1", True, True), ("log.simpleFoam", False, False)]


def test_transition_model_case_files(tmp_path):
    write_case(tmp_path, 8.75, 3e5, 0.1, SolverOverrides(), model="kOmegaSSTLM")
    assert "RASModel kOmegaSSTLM;" in (tmp_path / "constant" / "turbulenceProperties").read_text()
    rt = (tmp_path / "0" / "ReThetat").read_text()
    assert f"internalField uniform {retheta_t_freestream(0.001):.6g};" in rt
    assert (tmp_path / "0" / "gammaInt").exists()
    assert "div(phi,ReThetat)" in (tmp_path / "system" / "fvSchemes").read_text()
    assert 1100 < retheta_t_freestream(0.001) < 1200  # Langtry-Menter at Tu 0.1%
    write_case(tmp_path / "sst", 8.75, 3e5, 0.1, SolverOverrides())
    assert not (tmp_path / "sst" / "0" / "ReThetat").exists()


def test_recovery_eval_cache_is_consistent():
    p = Path(__file__).parent.parent / "evals" / "openfoam_recovery_deterministic.json"
    if not p.exists():
        pytest.skip("recovery evaluation not cached")
    rows = json.loads(p.read_text())["rows"]
    for r in rows:
        if "error" in r:
            continue
        levels = [a["level"] for a in r["attempts"]]
        assert levels[0] == 0 and len(set(levels)) == len(levels)  # never a repeated level
        assert r["recovered"] == (r["l0_failed"] and r["final_status"] == "converged")


def test_convergence_is_judged_by_the_criteria_not_by_a_quiet_exit():
    assert solver.convergence_status({"p": 7.7, "U": 7.0}, {"cl": 1e-4, "cd": 2e-4}) == ("converged", None)
    # the mesh study's growth-1.08 case: ended quietly at U 4.5 orders with steady coefficients
    status, sig = solver.convergence_status({"p": 5.4, "U": 4.5}, {"cl": 1e-4, "cd": 1e-4})
    assert status == "not_converged" and sig == "residuals_stalled:p5.4/U4.5"
    assert recovery.classify(sig, status) == "numerics"
    assert solver.convergence_status({"p": 2.0, "U": 2.0}, {"cl": 0.03, "cd": 0.08})[0] == "unsteady"


def test_ladder_stops_on_unsteady_separation(spec, tmp_path, monkeypatch):
    monkeypatch.setattr(solver, "evaluate", lambda *a, **k: _result("unsteady", "residuals_stalled:p2.0/U2.0"))
    r, attempts = solver.evaluate_with_recovery(P, spec, tmp_path, lambda f, t: pytest.fail("no recovery for unsteady"))
    assert r.status == "unsteady" and [a["level"] for a in attempts] == [0]
