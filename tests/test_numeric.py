import pytest
from conftest import good_stall

from swarm.agents.critic import merge_verdict
from swarm.critic.numeric import VALIDATION, ValidatorConfig, suggest_diagnosis, validate
from swarm.state import (
    BoundaryLayerSummary,
    CFDResult,
    Diagnosis,
    EvalRecord,
    Finding,
    Verdict,
    WingParams,
)

P = WingParams(main_camber=0.045, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=9.5)


def res(cl=-1.49, cd=0.0175, fidelity="xfoil", status="converged", **kw):
    return CFDResult(cid=P.cid, fidelity=fidelity, status=status, cl=cl, cd=cd, **kw)


def test_pass_at_xfoil_is_terminal(spec):
    rep = validate(res(), P, spec, [], stall=good_stall())
    assert rep.ok and rep.status == "PASS" and rep.terminal


def test_target_miss(spec):
    rep = validate(res(cl=-1.3), P, spec, [])
    assert rep.status == "TARGET_MISS" and not rep.terminal
    assert validate(res(cd=0.02), P, spec, []).status == "TARGET_MISS"


def test_neuralfoil_pass_is_not_terminal(spec):
    rep = validate(res(fidelity="neuralfoil", confidence=0.95), P, spec, [])
    assert rep.status == "PASS" and not rep.terminal


def test_fallback_result_flagged_and_never_terminal(spec):
    r = res(fidelity="neuralfoil", confidence=0.95, fallback_from="xfoil")
    assert r.lower_fidelity
    rep = validate(r, P, spec, [])
    assert rep.target_met and not rep.terminal
    assert any(c.name == "lower_fidelity" for c in rep.checks)


@pytest.mark.parametrize(
    "kw,check",
    [
        ({"cd": 0.003}, "drag_floor"),
        ({"cl": -2.6, "cd": 0.03}, "lift_ceiling"),
        ({"cl": -1.2, "cd": 0.0051}, "l_over_d"),
        ({"cl": 1.4}, "lift_sign"),
    ],
)
def test_non_physical(spec, kw, check):
    rep = validate(res(**kw), P, spec, [])
    assert rep.failure_class == "NON_PHYSICAL"
    assert check in [c.name for c in rep.checks if not c.ok]


def test_numerical_failures(spec):
    assert validate(res(status="not_converged", cl=None, cd=None), P, spec, []).failure_class == "NUMERICAL_FAILURE"
    assert validate(res(status="unsteady", cl=None, cd=None), P, spec, []).failure_class == "UNSTEADY"
    assert validate(None, P, spec, []).failure_class == "NUMERICAL_FAILURE"
    low = validate(res(fidelity="neuralfoil", confidence=0.4), P, spec, [])
    assert low.failure_class == "NUMERICAL_FAILURE"


def test_fidelity_gap_blocks_pass(spec):
    other = EvalRecord(
        generation=0, params=P, verdict=None, rationale="", result=res(cl=-1.70, fidelity="neuralfoil", confidence=0.9)
    )
    rep = validate(res(), P, spec, [other])
    assert rep.ok and rep.suspect and rep.status == "TARGET_MISS" and not rep.terminal


def test_thresholds_live_in_one_config(spec):
    assert VALIDATION.cd_floor == 0.005 and VALIDATION.fidelity_gap_max == 0.1
    strict = ValidatorConfig(cd_floor=0.02)
    assert validate(res(), P, spec, [], cfg=strict).failure_class == "NON_PHYSICAL"


def _v(status, sev="info"):
    return Verdict(
        status=status,
        diagnosis=Diagnosis(symptom="NONE"),
        confidence=0.5,
        findings=[
            Finding(observation="o", location="x/c 0.9", source="cp", consistent_with_numeric=True, severity=sev)
        ],
    )


def test_merge_verdict_asymmetry(spec):
    failed = validate(res(cd=0.003), P, spec, [])
    assert merge_verdict(failed, _v("PASS")).status == "NON_PHYSICAL"  # LLM cannot rescue
    ok = validate(res(), P, spec, [])
    assert merge_verdict(ok, _v("PASS", "fatal")).status == "NON_PHYSICAL"  # LLM can veto
    assert merge_verdict(ok, _v("TARGET_MISS")).status == "TARGET_MISS"  # downgrade allowed
    miss = validate(res(cl=-1.3), P, spec, [])
    assert merge_verdict(miss, _v("PASS")).status == "TARGET_MISS"  # no upgrade


def test_suggest_diagnosis_separation_vs_bubble(spec):
    sep = res(cl=-1.69, cd=0.038, bl=BoundaryLayerSummary(te_separation_xc=0.78, bubbles=[(0.01, 0.03)]))
    d = suggest_diagnosis(sep, spec)
    assert d.symptom == "TE_SEPARATION_MAIN" and d.x_over_c == (0.78, 1.0)
    bub = res(cl=-1.2, cd=0.012, bl=BoundaryLayerSummary(bubbles=[(0.4, 0.5)]))
    assert suggest_diagnosis(bub, spec).symptom == "INSUFFICIENT_LOADING"
    early = res(cl=-1.6, cd=0.05, bl=BoundaryLayerSummary(te_separation_xc=0.3))
    assert suggest_diagnosis(early, spec).symptom == "EARLY_STALL"
