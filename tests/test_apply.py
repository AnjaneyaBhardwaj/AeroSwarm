from swarm.cad.apply import NEAR_DUP_TOL, apply_delta, fallback_params, near_duplicate
from swarm.state import CFDResult, EvalRecord, ParamChange, ParamDelta, StrategyMemo, WingParams

BASE = WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=8.0)
MEMO = StrategyMemo(
    hypothesis="h",
    focus_params=["alpha_deg", "main_camber"],
    trust_radius=0.1,
    fidelity="neuralfoil",
    mode="reasoned_step",
)


def delta(name, value):
    return ParamDelta(
        changes=[ParamChange(name=name, new_value=value, mechanism="m", expected_dCl_sign=-1, expected_dCd_sign=1)]
    )


def test_accepts_valid_change(spec):
    r = apply_delta(BASE, delta("alpha_deg", 9.0), MEMO, spec, [])
    assert r.ok and r.params.alpha_deg == 9.0


def test_bounds_error_is_a_tool_error(spec):
    r = apply_delta(BASE, delta("main_camber", 0.2), MEMO, spec, [])
    assert not r.ok and r.error.kind == "bounds" and "> max 0.09" in r.error.msg


def test_trust_region(spec):
    r = apply_delta(BASE, delta("alpha_deg", 10.0), MEMO, spec, [])  # radius 0.1·16° = 1.6°
    assert not r.ok and r.error.kind == "trust_region" and "[6.4000, 9.6000]" in r.error.hint


def test_not_allowed_and_unknown(spec):
    assert apply_delta(BASE, delta("main_thickness", 0.13), MEMO, spec, []).error.kind == "not_allowed"
    assert apply_delta(BASE, delta("wingspan", 1.0), MEMO, spec, []).error.kind == "unknown_param"
    memo = MEMO.model_copy(update={"focus_params": ["flap_deflection_deg"]})
    assert apply_delta(BASE, delta("flap_deflection_deg", 1.0), memo, spec, []).error.kind == "not_allowed"


def test_duplicate_cid_returns_cached_numbers(spec):
    p = WingParams(**{**BASE.model_dump(), "alpha_deg": 9.0})
    rec = EvalRecord(
        generation=1,
        params=p,
        verdict=None,
        rationale="",
        result=CFDResult(cid=p.cid, fidelity="neuralfoil", status="converged", cl=-1.4, cd=0.015),
    )
    r = apply_delta(BASE, delta("alpha_deg", 9.00002), MEMO, spec, [rec])  # quantizes to 9.0
    assert not r.ok and r.error.kind == "duplicate" and "Cl=-1.400, Cd=0.0150" in r.error.msg
    # same cid at a different fidelity is not a duplicate
    assert apply_delta(BASE, delta("alpha_deg", 9.0), MEMO.model_copy(update={"fidelity": "xfoil"}), spec, [rec]).ok


def test_no_change(spec):
    assert apply_delta(BASE, delta("alpha_deg", 8.00001), MEMO, spec, []).error.kind == "no_change"


def test_fallback_stays_in_trust_region_and_is_new(spec):
    p = fallback_params(BASE, MEMO, spec, [], seed=1)
    assert p.cid != BASE.cid
    assert abs(p.alpha_deg - BASE.alpha_deg) <= 0.1 * 16 * 0.25 + 1e-9
    assert p.main_thickness == BASE.main_thickness  # outside the focus set: unchanged


def test_near_duplicate_is_rejected_with_the_existing_result(spec):
    base = WingParams(main_camber=0.05, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=8.0)
    seen = base.model_copy(update={"alpha_deg": 9.0})
    rec = EvalRecord(
        generation=3,
        params=seen,
        result=CFDResult(cid=seen.cid, fidelity="neuralfoil", status="converged", cl=-1.6, cd=0.017),
        verdict=None,
        rationale="",
    )
    memo = MEMO.model_copy(update={"trust_radius": 0.3})
    near = ParamDelta(
        changes=[
            ParamChange(name="alpha_deg", new_value=9.03, mechanism="m", expected_dCl_sign=-1, expected_dCd_sign=1)
        ]
    )
    res = apply_delta(base, near, memo, spec, [rec])
    assert not res.ok and res.error.kind == "duplicate"
    assert f"within tolerance of {seen.cid} (gen 3), already evaluated: Cl=-1.600, Cd=0.0170" in res.error.msg
    assert NEAR_DUP_TOL["alpha_deg"] == 0.05 and NEAR_DUP_TOL["main_camber"] == 0.002
    far = near.model_copy(update={"changes": [near.changes[0].model_copy(update={"new_value": 9.06})]})
    assert apply_delta(base, far, memo, spec, [rec]).ok  # outside 0.05 deg
    other_fid = memo.model_copy(update={"fidelity": "xfoil"})
    assert apply_delta(base, near, other_fid, spec, [rec]).ok  # a different tier is not a duplicate
    assert near_duplicate(seen.model_copy(update={"main_camber": 0.0515}), [rec], "neuralfoil") is rec
    assert near_duplicate(seen.model_copy(update={"main_camber": 0.0525}), [rec], "neuralfoil") is None
