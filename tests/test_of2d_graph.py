"""OpenFOAM (of2d) in the agent graph (milestone 5 part 3), offline: the Chief's of2d rules, a promotion solved
through the recovery ladder (a fake OpenFOAM), the XFoil fallback for an unsimulatable design, the validator's
OpenFOAM checks, and the report section."""

import json

import pytest

from swarm.agents.chief import sanitize
from swarm.critic.numeric import validate
from swarm.ledger import RunFiles
from swarm.llm.client import TraceLogger
from swarm.llm.mock import MockClient
from swarm.run import run
from swarm.solvers.openfoam import solver as of_solver
from swarm.state import CFDResult, Diagnosis, EvalRecord, StrategyMemo, Verdict, WingParams

P = WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=4.0)


def _rec(p, fidelity):
    r = CFDResult(cid=p.cid, fidelity=fidelity, status="converged", cl=-1.2, cd=0.015)
    return EvalRecord(generation=0, params=p, result=r, verdict=Verdict(status="TARGET_MISS",
                      diagnosis=Diagnosis(symptom="NONE"), confidence=0.5), rationale="")  # fmt: skip


def _memo(**kw):
    base = {"hypothesis": "h", "focus_params": ["alpha_deg"], "trust_radius": 0.1, "fidelity": "of2d",
            "mode": "reasoned_step", "promote_cid": P.cid}  # fmt: skip
    return StrategyMemo(**(base | kw))


def test_chief_of2d_rules(spec):
    ledger_nf = [_rec(P, "neuralfoil")]
    m, ev = sanitize(_memo(), {"spec": spec, "ledger": ledger_nf + [_rec(P, "xfoil")], "of2d_allowed": False})
    assert m.fidelity == "xfoil" and any(e["event"] == "fidelity_unavailable" for e in ev)  # not allowed in this run
    m, ev = sanitize(_memo(), {"spec": spec, "ledger": ledger_nf, "of2d_allowed": True})
    assert m.fidelity == "xfoil" and any(e["event"] == "of2d_needs_xfoil_result" for e in ev)
    m, ev = sanitize(_memo(promote_cid=None), {"spec": spec, "ledger": ledger_nf, "of2d_allowed": True})
    assert m.fidelity == "xfoil"  # a fresh design never goes straight to OpenFOAM
    m, ev = sanitize(_memo(), {"spec": spec, "ledger": ledger_nf + [_rec(P, "xfoil")], "of2d_allowed": True})
    assert m.fidelity == "of2d" and m.promote_cid == P.cid and not ev


class Of2dMock(MockClient):
    """The rule-based mock, plus: once a design has an XFoil result, promote it to of2d (once). Tests only."""

    def __init__(self, trace, run_dir):
        super().__init__(trace)
        self.run_dir = run_dir

    def _chief(self, f):
        memo = super()._chief(f)
        ledger = RunFiles(self.run_dir).read_ledger() if (self.run_dir / "ledger.jsonl").exists() else []
        done = any(r.result.fidelity == "of2d" or r.result.fallback_from == "of2d" for r in ledger)
        xf = [r for r in ledger if r.result.fidelity == "xfoil" and not r.result.fallback_from]
        if xf and not done:
            return memo.model_copy(
                update={"fidelity": "of2d", "promote_cid": xf[-1].params.cid, "mode": "reasoned_step"}
            )
        return memo


def _fake_of2d(converge: bool, calls: list):
    def fake(params, spec, run_dir, choose, *a, **k):
        failure = {"signature": "residual_growth@it400:Ux", "status": "diverged", "cid": params.cid, "alpha": 4}
        action = choose(failure, [])
        calls.append(action.level)
        attempts = [
            {"level": 0, "status": "diverged", "signature": failure["signature"]},
            {"level": action.level, "rationale": action.rationale, "status": "converged" if converge else "diverged"},
        ]
        if not converge:
            attempts.append({"level": 5, "unsimulatable": True, "rationale": "exhausted"})
            return CFDResult(cid=params.cid, fidelity="of2d", status="diverged", failure_signature="x"), attempts
        r = CFDResult(
            cid=params.cid, fidelity="of2d", status="converged", cl=-0.9, cd=0.03, solver_level=action.level,
            residual_drop_orders={"p": 7.0, "U": 7.0}, coeff_rel_std_window={"cl": 1e-4, "cd": 2e-4},
            yplus=(0.1, 0.3, 0.6), mesh={"ok": True, "max_non_ortho": 40.0, "failed_checks": 0},
        )  # fmt: skip
        return r, attempts

    return fake


@pytest.mark.parametrize("converge", [True, False])
def test_of2d_promotion_runs_the_ladder_or_falls_back_to_xfoil(
    spec, start, fake_xfoil, tmp_path, monkeypatch, converge
):
    fake_xfoil(cl_offset=0.4)  # XFoil misses the target, so the run continues past the first XFoil result
    calls: list = []
    monkeypatch.setattr(of_solver, "evaluate_with_recovery", _fake_of2d(converge, calls))
    d = tmp_path / "of"
    llm = Of2dMock(TraceLogger(d / "traces.jsonl"), d)
    final = run(spec.model_copy(update={"max_evals": 12}), start, run_id="of", runs_root=tmp_path, llm=llm, of2d=True)
    events = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()]
    assert calls == [1]  # the CFD agent (mock policy) chose L1 for a late (numerics) failure
    assert any(e.get("event") == "of2d_recovery" and e["level"] == 1 for e in events)
    report = (d / "report.md").read_text()
    if converge:
        of = [r for r in final["ledger"] if r.result.fidelity == "of2d"]
        assert len(of) == 1 and of[0].result.solver_level == 1
        assert {c for c in of[0].failed_checks} <= {"fidelity_gap", "te_separation"}  # converged and checked
        assert "## OpenFOAM recovery ladder" in report and "recovered above L0: 1" in report
    else:
        fb = [r for r in final["ledger"] if r.result.fallback_from == "of2d"]
        assert len(fb) == 1 and fb[0].result.fidelity == "xfoil" and fb[0].result.lower_fidelity
        assert any(e.get("event") == "of2d_unsimulatable" for e in events)
        assert "could not be converged (evaluated at XFoil instead): 1" in report
    assert json.loads((d / "meta.json").read_text())["of2d"] is True


def test_without_the_flag_no_of2d_runs(spec, start, fake_xfoil, tmp_path, monkeypatch):
    fake_xfoil(cl_offset=0.4)
    monkeypatch.setattr(of_solver, "evaluate_with_recovery", lambda *a, **k: pytest.fail("OpenFOAM must not run"))
    d = tmp_path / "no"
    final = run(spec.model_copy(update={"max_evals": 8}), start, run_id="no", runs_root=tmp_path,
                llm=Of2dMock(TraceLogger(d / "traces.jsonl"), d))  # fmt: skip
    assert not any(r.result.fidelity == "of2d" for r in final["ledger"])
    events = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()]
    assert any(e.get("event") == "fidelity_unavailable" and e["requested"] == "of2d" for e in events)


def _of2d(**kw):
    base = {"cid": P.cid, "fidelity": "of2d", "status": "converged", "cl": -0.9, "cd": 0.02,
            "residual_drop_orders": {"p": 6.0, "U": 6.0}, "coeff_rel_std_window": {"cl": 1e-4, "cd": 1e-4},
            "yplus": (0.1, 0.4, 0.9), "mesh": {"ok": True, "max_non_ortho": 40.0, "failed_checks": 0}}  # fmt: skip
    return CFDResult(**(base | kw))


def test_validator_openfoam_checks(spec):
    ok = validate(_of2d(), P, spec, [])
    names = {c.name: c for c in ok.checks}
    assert names["residuals"].ok and names["mesh"].ok and names["yplus"].ok and names["coefficient_window"].ok
    assert ok.ok
    stalled = validate(_of2d(residual_drop_orders={"p": 2.0, "U": 2.5}), P, spec, [])
    assert stalled.failure_class == "NUMERICAL_FAILURE"
    unsteady = validate(
        _of2d(residual_drop_orders={"p": 2.0, "U": 2.5}, coeff_rel_std_window={"cl": 0.03, "cd": 0.05}), P, spec, []
    )
    assert unsteady.failure_class == "UNSTEADY"  # stalled residuals with moving coefficients: a design signal
    bad_mesh = validate(_of2d(mesh={"ok": False, "failed_checks": 2}), P, spec, [])
    assert bad_mesh.failure_class == "NUMERICAL_FAILURE"
    thick = validate(_of2d(yplus=(1.0, 12.0, 30.0)), P, spec, [])
    assert thick.ok and thick.suspect and not next(c for c in thick.checks if c.name == "yplus").ok
