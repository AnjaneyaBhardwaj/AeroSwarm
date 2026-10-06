"""Search-loop fixes after the first live run (docs/PROGRESS.md, sessions 6-7).

1. The CAD brief's diagnosis is for the design being modified (same cid).
2. Directional focus_params; the CAD follows or gives a logged override reason; the Chief
   sees its previous hypotheses with their outcomes.
3. Parent = best design that passed at its fidelity, else least constraint violation.
4. A failed stall margin or NeuralFoil screen is diagnosed EARLY_STALL, with numbers.
5. A fresh design sent straight to XFoil is screened unless the Chief overrides (logged).
"""

import json

import pytest
from conftest import good_stall

from swarm.agents import critic as critic_agent
from swarm.briefs import cad_brief, chief_brief
from swarm.cad.apply import apply_delta
from swarm.critic.numeric import suggest_diagnosis, validate
from swarm.ledger import select_parent, violation
from swarm.llm.client import ScriptedClient
from swarm.run import run
from swarm.state import (
    BoundaryLayerSummary,
    CFDResult,
    Diagnosis,
    EvalRecord,
    ParamChange,
    ParamDelta,
    StallMargin,
    StrategyMemo,
    SurrogateScreen,
    Verdict,
    WingParams,
)


def wp(alpha, camber=0.05):
    return WingParams(main_camber=camber, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=alpha)


def rec(p, cl, cd=0.017, fid="xfoil", status="TARGET_MISS", symptom="NONE", gen=1, stall=None, screen=None, sep=None):
    r = CFDResult(
        cid=p.cid,
        fidelity=fid,
        status="converged",
        cl=cl,
        cd=cd,
        bl=BoundaryLayerSummary(te_separation_xc=sep) if fid == "xfoil" else None,
    )
    v = Verdict(status=status, diagnosis=Diagnosis(symptom=symptom), confidence=0.6)
    return EvalRecord(generation=gen, params=p, result=r, verdict=v, rationale="", stall_margin=stall, screen=screen)


def memo(focus, fidelity="neuralfoil", radius=0.3, **kw):
    return StrategyMemo(
        hypothesis="h", focus_params=focus, trust_radius=radius, fidelity=fidelity, mode="reasoned_step", **kw
    )


def no_margin(slope=0.02, seps=(None, None, None)):
    return StallMargin(
        alphas_deg=[9.0, 10.0, 11.0],
        cls=[-1.5, -1.5 - slope, -1.5 - 2 * slope],
        levels=[0, 0, 0],
        te_separation_xc=list(seps),
        slopes=[slope, slope],
        dcl_dalpha=slope,
        threshold=0.05,
        ok=False,
    )


def screen(ok=True, slope=0.08, sep=False):
    return SurrogateScreen(
        alphas_deg=[9.0, 10.0, 11.0],
        cls=[-1.5, -1.5 - slope, -1.5 - 2 * slope],
        slopes=[slope, slope],
        dcl_dalpha=slope,
        stall_threshold=0.05,
        stall_ok=slope >= 0.05,
        te_shape_factor=[5.0 if sep else 2.5, 3, 4],
        sep_xc=0.95 if sep else None,
        h_sep=4.25,
        sep_warning=sep,
        ok=ok and slope >= 0.05 and not sep,
    )


def delta(name, value, reason=""):
    ch = ParamChange(name=name, new_value=value, mechanism="m", expected_dCl_sign=-1, expected_dCd_sign=1)
    return ParamDelta(changes=[ch.model_copy(update={"override_reason": reason})])


# ----------------------------------------------------------- 1. diagnosis of the base cid


def test_cad_brief_diagnosis_is_for_the_design_being_modified(spec):
    base, other = wp(8.0), wp(9.0)
    base_rec = rec(base, -1.45, symptom="INSUFFICIENT_LOADING")
    latest = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="EXCESS_PRESSURE_DRAG"), confidence=0.6)
    state = {"spec": spec, "strategy": memo(["alpha_deg"]), "verdict": latest, "ledger": [base_rec, rec(other, -1.6)]}
    b = cad_brief(state, base, base_rec, {})
    assert b.facts["diagnosis_cid"] == b.facts["base_cid"] == base.cid
    assert b.facts["diagnosis"]["symptom"] == "INSUFFICIENT_LOADING"  # not the latest verdict's
    assert f"## Critic diagnosis of this design ({base.cid})" in b.user and "EXCESS_PRESSURE_DRAG" not in b.user


def test_cad_diagnosis_follows_the_parent_not_the_last_evaluation(spec, start, tmp_path):
    """Gen 1 moves away from the target, so gen 2's parent is the baseline again while the latest
    verdict belongs to gen 1's design: the CAD brief must carry the baseline's diagnosis."""
    m = memo(["alpha_deg"])
    v0 = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="INSUFFICIENT_LOADING"), confidence=0.6)
    v1 = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="EXCESS_PRESSURE_DRAG"), confidence=0.6)
    llm = ScriptedClient([m, v0, m, delta("alpha_deg", 2.0), v1, m, delta("alpha_deg", 5.0), v0])
    final = run(spec.model_copy(update={"max_evals": 3}), start, run_id="p", runs_root=tmp_path, llm=llm)
    base, worse = final["ledger"][0], final["ledger"][1]
    assert (
        worse.verdict.diagnosis.symptom == "EXCESS_PRESSURE_DRAG" and final["ledger"][2].parent_cid == base.params.cid
    )
    gen2 = [c for c in llm.calls if c["role"] == "cad"][-1]["user"]
    assert f"## Critic diagnosis of this design ({base.params.cid})" in gen2
    assert "INSUFFICIENT_LOADING" in gen2 and "EXCESS_PRESSURE_DRAG" not in gen2


# ----------------------------------------------------------- 2. directions


def test_change_against_the_chiefs_direction_needs_a_reason(spec):
    base = wp(8.0)
    m = memo([{"name": "alpha_deg", "direction": "-"}])
    res = apply_delta(base, delta("alpha_deg", 9.0), m, spec, [])
    assert not res.ok and res.error.kind == "direction" and "asked for -" in res.error.msg
    res = apply_delta(base, delta("alpha_deg", 9.0, "lift-curve slope still healthy"), m, spec, [])
    assert res.ok and res.disagreements == [
        {"param": "alpha_deg", "chief": "-", "cad": "+", "reason": "lift-curve slope still healthy"}
    ]
    assert apply_delta(base, delta("alpha_deg", 7.0), m, spec, []).ok  # follows: no reason needed
    assert apply_delta(base, delta("alpha_deg", 9.0), memo(["alpha_deg"]), spec, []).ok  # free


def test_graph_logs_chief_cad_disagreement_and_chief_sees_history(spec, start, tmp_path):
    m1 = memo([{"name": "alpha_deg", "direction": "-"}])
    v = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="INSUFFICIENT_LOADING"), confidence=0.6)
    script = [
        m1,
        v,  # gen 0: baseline
        m1,
        delta("alpha_deg", 5.0),
        delta("alpha_deg", 5.0, "needs more loading"),
        v,  # gen 1: rejected, then kept
        m1,
        delta("alpha_deg", 3.5),
        v,  # gen 2: follows the direction
    ]
    llm = ScriptedClient(script)
    run(spec.model_copy(update={"max_evals": 3}), start, run_id="d", runs_root=tmp_path, llm=llm)
    assert not llm.responses
    events = [json.loads(x) for x in (tmp_path / "d" / "events.jsonl").read_text().splitlines()]
    rej = [e for e in events if e.get("event") == "proposal_rejected"]
    assert len(rej) == 1 and rej[0]["error"]["kind"] == "direction" and rej[0]["gen"] == 1
    dis = [e for e in events if e.get("event") == "chief_cad_disagreement"]
    assert [(e["gen"], e["chief"], e["cad"], e["reason"]) for e in dis] == [(1, "-", "+", "needs more loading")]
    chief_calls = [c for c in llm.calls if c["role"] == "chief"]
    last = chief_calls[-1]["user"]
    assert "## Your previous hypotheses and what happened" in last
    assert "- gen 0: h -> " in last and "- gen 1: h -> " in last and "at neuralfoil" in last


# ----------------------------------------------------------- 3. parent selection


def test_parent_is_a_passing_design_and_xfoil_overrides_a_neuralfoil_pass(spec):
    a, b = wp(8.0), wp(8.5)
    ledger = [
        rec(a, -1.50, fid="neuralfoil", status="PASS", gen=1),
        rec(a, -1.50, status="TARGET_MISS", stall=no_margin(), gen=2),  # XFoil rejects a
        rec(b, -1.52, fid="neuralfoil", status="PASS", gen=3),
    ]
    parent, why = select_parent(ledger, spec)
    assert parent.params.cid == b.cid and why == "passed all checks at neuralfoil"


def test_without_a_pass_the_parent_has_the_least_constraint_violation(spec):
    stalled = rec(wp(9.0), -1.500, stall=no_margin(0.01), gen=1)  # objective 0, but no stall margin
    healthy = rec(wp(7.0), -1.45, screen=screen(slope=0.09), gen=2)  # 0.02 outside the box
    separated = rec(wp(9.5), -1.49, sep=0.9, gen=3)
    v = {r.params.cid: violation(r, spec) for r in (stalled, healthy, separated)}
    assert v[stalled.params.cid]["stall"] == pytest.approx(0.8) and v[stalled.params.cid]["box"] == 0
    assert v[separated.params.cid]["separation"] == 1
    parent, why = select_parent([stalled, healthy, separated], spec)
    assert parent is healthy and why.startswith("nothing passed; least constraint violation")


def test_screen_separation_at_the_probes_counts_as_separation_at_neuralfoil(spec):
    """The screen's alpha+1/+2 TE-H warning is the NeuralFoil analogue of XFoil's probe-range separation:
    a design the screen fails on it is not violation-free (it was before session 13)."""
    sc = screen().model_copy(update={"probe_h_max": 4.35, "probe_sep": True, "ok": False})
    probe = rec(wp(8.0), -1.50, fid="neuralfoil", screen=sc)
    clean = rec(wp(7.0), -1.50, fid="neuralfoil", screen=screen())
    assert violation(probe, spec)["separation"] == 1 and violation(clean, spec)["total"] == 0
    assert select_parent([probe, clean], spec)[0] is clean


# ----------------------------------------------------------- 4. EARLY_STALL


def test_failed_stall_margin_is_early_stall_with_numbers(spec):
    r = CFDResult(cid="c", fidelity="xfoil", status="converged", cl=-1.49, cd=0.017, bl=BoundaryLayerSummary())
    d = suggest_diagnosis(r, spec, stall=no_margin(0.02, (None, 0.97, 0.91)))
    assert d.symptom == "EARLY_STALL" and d.x_over_c == (0.97, 1.0)
    ev = " | ".join(d.evidence)
    assert "margin 0.020 vs threshold 0.05 (short by 0.030)" in ev and "TE separation first at alpha 10 deg" in ev
    assert suggest_diagnosis(r, spec, stall=good_stall()).symptom == "NONE"


def test_failed_screen_is_early_stall_only_at_neuralfoil(spec):
    nf = CFDResult(cid="c", fidelity="neuralfoil", status="converged", cl=-1.49, cd=0.017, confidence=0.9)
    d = suggest_diagnosis(nf, spec, screen=screen(slope=0.03, sep=True))
    assert d.symptom == "EARLY_STALL" and "separation) first at alpha 9 deg" in " | ".join(d.evidence)
    xf = nf.model_copy(update={"fidelity": "xfoil", "confidence": None})
    assert suggest_diagnosis(xf, spec, screen=screen(slope=0.03)).symptom != "EARLY_STALL"  # XFoil decides there


def test_critic_cannot_relabel_a_stall_failure(spec):
    p = wp(9.5, camber=0.045)
    r = CFDResult(cid=p.cid, fidelity="xfoil", status="converged", cl=-1.49, cd=0.0175, solver_level=0)
    stall = no_margin(0.02)
    rep = validate(r, p, spec, [], stall=stall)
    llm = ScriptedClient([Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="NONE"), confidence=0.9)])
    v = critic_agent.review(llm, {"spec": spec, "result": r, "params": p, "numeric": rep, "stall": stall}, None)
    assert v.diagnosis.symptom == "EARLY_STALL" and any("short by 0.030" in e for e in v.diagnosis.evidence)


# ----------------------------------------------------------- 5. direct-to-XFoil screening


# NeuralFoil at alpha 10 from the start (t 0.13): Cl -1.6677, Cd 0.0181, screen failed (slope 0.014, TE H 4.76)
IN_BOX = {"target_cl": -1.67, "cd_max": 0.020}


def _direct_run(spec, start, tmp_path, run_id, alpha=10.0, more=(), **memo_kw):
    m0 = memo(["alpha_deg"])
    m1 = memo([{"name": "alpha_deg", "direction": "+"}], fidelity="xfoil", radius=0.4, **memo_kw)
    v = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="INSUFFICIENT_LOADING"), confidence=0.6)
    llm = ScriptedClient([m0, v, m1, delta("alpha_deg", alpha), v, *more])
    s = spec.model_copy(update={"max_evals": 2 + len(more) // 3})
    final = run(s, start, run_id=run_id, runs_root=tmp_path, llm=llm)
    events = [json.loads(x) for x in (tmp_path / run_id / "events.jsonl").read_text().splitlines()]
    return final, events, llm


def test_direct_xfoil_design_is_screened_first(spec, start, fake_xfoil, tmp_path):
    calls = fake_xfoil()
    final, events, _ = _direct_run(spec, start, tmp_path, "s")
    out = [e for e in events if e.get("event") == "direct_xfoil_screened_out"]
    assert len(out) == 1 and out[0]["requested"] == "xfoil" and out[0]["reasons"]
    assert final["ledger"][-1].result.fidelity == "neuralfoil" and not calls  # XFoil never ran


def test_chief_can_override_the_screen_with_a_logged_reason(spec, start, fake_xfoil, tmp_path):
    calls = fake_xfoil()
    s = spec.model_copy(update=IN_BOX)
    final, events, _ = _direct_run(s, start, tmp_path, "o", screen_override="map the stall boundary at XFoil")
    ov = [e for e in events if e.get("event") == "screen_override"]
    assert len(ov) == 1 and ov[0]["reason"] == "map the stall boundary at XFoil" and ov[0]["reasons"]
    assert not any(e.get("event") in ("direct_xfoil_screened_out", "screen_override_refused") for e in events)
    assert final["ledger"][-1].result.fidelity == "xfoil" and calls


# ----------------------------------------------------------- deadlock: adopt or lock


def _deadlock_state(spec, chief="-", cad="+"):
    d = {"event": "chief_cad_disagreement", "gen": 3, "param": "alpha_deg", "chief": chief, "cad": cad}
    return {
        "spec": spec,
        "ledger": [],
        "generation": 4,
        "history": [{"gen": 3, "hypothesis": "h", "focus": [], "fidelity": "neuralfoil"}],
        "events": [d | {"reason": "needs more loading", "cid": "x"}],
    }


def test_chief_must_adopt_or_lock_after_an_override(spec):
    from swarm.agents.chief import sanitize

    st = _deadlock_state(spec)
    cases = {
        ("-", False): (("-", True), "deadlock_coerced"),  # restated without a lock -> locked
        ("free", False): (("+", False), "deadlock_coerced"),  # free -> adopts the CAD's direction
        ("+", False): (("+", False), "chief_adopted_direction"),
        ("-", True): (("-", True), "chief_locked_direction"),
    }
    for (direction, locked), ((want_dir, want_lock), event) in cases.items():
        m = memo([{"name": "alpha_deg", "direction": direction, "locked": locked}, "main_camber"])
        out, events = sanitize(m, st)
        f = out.focus_params[0]
        assert (f.direction, f.locked) == (want_dir, want_lock), (direction, locked)
        assert [e["event"] for e in events] == [event] and events[0]["param"] == "alpha_deg"
        assert out.focus_params[1].name == "main_camber"  # untouched
    m = memo(["main_camber"])  # dropping the parameter also resolves it
    assert sanitize(m, st) == (m, [])


def test_locked_direction_cannot_be_overridden(spec):
    m = memo([{"name": "alpha_deg", "direction": "-", "locked": True}])
    res = apply_delta(wp(8.0), delta("alpha_deg", 9.0, "physics says so"), m, spec, [])
    assert not res.ok and res.error.kind == "direction" and "locked" in res.error.msg


def test_chief_brief_shows_last_generations_overrides(spec):
    b = chief_brief(_deadlock_state(spec), {})
    assert b.facts["cad_overrides"] == [
        {"param": "alpha_deg", "chief": "-", "cad": "+", "reason": "needs more loading"}
    ]
    assert "- alpha_deg: you said decrease, CAD went increase: needs more loading" in b.user
    assert "locked=true" in b.user


def test_graph_locks_a_restated_direction_and_the_cad_must_follow(spec, start, tmp_path):
    m = memo([{"name": "alpha_deg", "direction": "-"}])
    v = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="INSUFFICIENT_LOADING"), confidence=0.6)
    script = [
        m,
        v,  # gen 0
        m,
        delta("alpha_deg", 5.0, "needs more loading"),
        v,  # gen 1: override logged
        m,
        delta("alpha_deg", 6.0, "still needs loading"),
        delta("alpha_deg", 3.0),
        v,  # gen 2: locked
    ]
    llm = ScriptedClient(script)
    run(spec.model_copy(update={"max_evals": 3}), start, run_id="l", runs_root=tmp_path, llm=llm)
    assert not llm.responses
    events = [json.loads(x) for x in (tmp_path / "l" / "events.jsonl").read_text().splitlines()]
    co = [e for e in events if e.get("event") == "deadlock_coerced"]
    assert len(co) == 1 and co[0]["gen"] == 2 and co[0]["resolution"].startswith("locked")
    rej = [e for e in events if e.get("event") == "proposal_rejected"]
    assert len(rej) == 1 and rej[0]["gen"] == 2 and "locked" in rej[0]["error"]["msg"]
    assert len([e for e in events if e.get("event") == "chief_cad_disagreement"]) == 1
    gen2_chief = [c for c in llm.calls if c["role"] == "chief"][2]["user"]
    assert "- alpha_deg: you said decrease, CAD went increase: needs more loading" in gen2_chief
