"""Screen overrides (cap, in-box rule, track record) and the stall_untested label."""

from __future__ import annotations

import json

from test_loop_fixes import IN_BOX, _direct_run, delta, memo, rec, wp
from test_screen import nf_rec, scr

from swarm.agents.chief import sanitize
from swarm.briefs import chief_brief
from swarm.ledger import RunFiles, row
from swarm.overrides import MAX_SCREEN_OVERRIDES, track_record
from swarm.state import Diagnosis, StallMargin, StrategyMemo, Verdict


def _promote(cid, reason="the shortfall is small; let XFoil decide"):
    return StrategyMemo(
        hypothesis="h",
        focus_params=["alpha_deg"],
        trust_radius=0.1,
        fidelity="xfoil",
        mode="reasoned_step",
        promote_cid=cid,
        screen_override=reason,
    )


def _used(n):
    return [{"event": "promotion_screen_override", "gen": i, "cid": f"c{i}", "reason": "r"} for i in range(n)]


# ----------------------------------------------------------- override rules (promotion)


def test_promotion_override_needs_the_neuralfoil_result_inside_the_box(spec):
    p = wp(8.5)
    blocked = scr(stall_ok=False, slope=0.04)
    inside = [nf_rec(p, -1.52, screen=blocked)]  # |dCl| 0.02 <= tol 0.03
    out, ev = sanitize(_promote(p.cid), {"spec": spec, "ledger": inside, "generation": 2})
    assert out.promote_cid == p.cid and [e["event"] for e in ev] == ["promotion_screen_override"]
    window = [nf_rec(p, -1.55, screen=blocked)]  # within 2*tol (promotion window), outside the box
    out, ev = sanitize(_promote(p.cid), {"spec": spec, "ledger": window, "generation": 2})
    assert out.promote_cid is None and out.fidelity == "neuralfoil" and out.screen_override == ""
    assert [e["event"] for e in ev] == ["screen_override_refused", "promotion_blocked_by_screen"]
    assert "not inside the target box" in ev[0]["why"] and ev[0]["reason"].startswith("the shortfall")
    over_cd = [nf_rec(p, -1.50, cd=0.019, screen=blocked)]  # Cd over cd_max 0.018
    out, ev = sanitize(_promote(p.cid), {"spec": spec, "ledger": over_cd, "generation": 2})
    assert out.promote_cid is None and ev[0]["event"] == "screen_override_refused"


def test_at_most_two_overrides_per_run(spec):
    assert MAX_SCREEN_OVERRIDES == 2
    p = wp(8.5)
    ledger = [nf_rec(p, -1.51, screen=scr(stall_ok=False, slope=0.04))]
    st = {"spec": spec, "ledger": ledger, "generation": 5, "events": _used(1)}
    out, ev = sanitize(_promote(p.cid), st)
    assert out.promote_cid == p.cid and ev[0]["event"] == "promotion_screen_override"
    st["events"] = _used(2)
    out, ev = sanitize(_promote(p.cid), st)
    assert out.promote_cid is None and ev[0]["event"] == "screen_override_refused"
    assert ev[0]["why"] == "override cap reached (2 of 2 used this run)"


def test_no_reason_no_override(spec):
    p = wp(8.5)
    ledger = [nf_rec(p, -1.51, screen=scr(stall_ok=False, slope=0.04))]
    out, ev = sanitize(_promote(p.cid, reason=""), {"spec": spec, "ledger": ledger, "generation": 2})
    assert out.promote_cid is None and [e["event"] for e in ev] == ["promotion_blocked_by_screen"]


# ----------------------------------------------------------- override rules (direct to XFoil)


def test_direct_override_is_refused_outside_the_box(spec, start, fake_xfoil, tmp_path):
    calls = fake_xfoil()
    final, events, _ = _direct_run(spec, start, tmp_path, "r", screen_override="let XFoil decide")
    ref = [e for e in events if e.get("event") == "screen_override_refused"]
    assert len(ref) == 1 and ref[0]["kind"] == "direct to XFoil" and "not inside the target box" in ref[0]["why"]
    assert any(e.get("event") == "direct_xfoil_screened_out" for e in events)
    assert not any(e.get("event") == "screen_override" for e in events)
    assert final["ledger"][-1].result.fidelity == "neuralfoil" and not calls


def test_a_screen_pass_does_not_use_an_override(spec, start, fake_xfoil, tmp_path):
    calls = fake_xfoil()
    final, events, _ = _direct_run(spec, start, tmp_path, "p", alpha=5.0, screen_override="just in case")
    assert not any(e.get("event", "").startswith("screen_override") for e in events)
    assert final["ledger"][-1].result.fidelity == "xfoil" and calls


def test_track_record_reaches_the_next_chief_brief_and_the_report(spec, start, fake_xfoil, tmp_path):
    """An in-box direct override whose XFoil result comes back less loaded (outside the box): the
    stall probe does not run, so the record says stall untested and the report excludes it from the
    screen evidence."""
    fake_xfoil(cl_offset=0.1)
    v = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="INSUFFICIENT_LOADING"), confidence=0.6)
    s = spec.model_copy(update=IN_BOX)
    more = [memo(["alpha_deg"]), delta("alpha_deg", 9.0), v]
    final, events, llm = _direct_run(s, start, tmp_path, "t", more=more, screen_override="probe the boundary")
    x = next(r for r in final["ledger"] if r.result.fidelity == "xfoil")
    assert x.stall_untested and x.stall_margin is None
    gen2 = [c for c in llm.calls if c["role"] == "chief"][-1]["user"]
    assert "## Your screen overrides this run and what XFoil found\nUsed 1 of 2;" in gen2
    assert f"- gen 1 direct to XFoil of {x.params.cid}: XFoil fail (Cl " in gen2
    assert "stall untested (probe not run): no evidence about the screen" in gen2
    assert "stall untested (XFoil stall probe not run: no evidence about the screen)" in gen2  # history
    report = (tmp_path / "t" / "report.md").read_text()
    assert "## Screen overrides" in report and f"| {x.params.cid} | xfoil | TARGET_MISS |" in report
    assert "| untested |" in report
    note = "Not evidence about the screen (1 XFoil result(s) with the stall probe not run, stall_untested)"
    assert f"{note}: gen 1 `{x.params.cid}`" in report


# ----------------------------------------------------------- track record


def _probe(ok, slope):
    return StallMargin(
        alphas_deg=[9, 10, 11],
        cls=[-1.5, -1.5 - slope, -1.5 - 2 * slope],
        levels=[0, 0, 0],
        dcl_dalpha=slope,
        threshold=0.05,
        ok=ok,
    )


def test_track_record_outcomes(spec):
    a, b, c, d = wp(8.0), wp(8.5), wp(9.0), wp(9.5)
    ledger = [
        rec(a, -1.40),  # XFoil outside the box, no probe: stall untested
        rec(b, -1.50, stall=_probe(False, 0.02)),  # probe ran and failed
        rec(c, -1.50, status="PASS", stall=_probe(True, 0.08)),  # PASS
    ]
    events = [
        {"event": "promotion_screen_override", "gen": 1, "cid": a.cid},
        {"event": "promotion_screen_override", "gen": 2, "cid": b.cid},
        {"event": "screen_override", "gen": 3, "cid": c.cid},
        {"event": "screen_override_refused", "gen": 4, "cid": d.cid, "kind": "promotion", "why": "cap"},
    ]
    tr = track_record({"spec": spec, "ledger": ledger, "events": events})
    assert [t["kind"] for t in tr] == ["promotion", "promotion", "direct to XFoil", "promotion"]
    assert tr[0]["outcome"].endswith("stall untested (probe not run): no evidence about the screen")
    assert (
        tr[1]["outcome"].startswith("XFoil fail (Cl -1.5000, Cd 0.01700): stall_margin")
        and "untested" not in tr[1]["outcome"]
    )
    assert tr[2]["outcome"] == "XFoil PASS (Cl -1.5000, Cd 0.01700): the screen was wrong here"
    assert tr[3]["outcome"] == "refused: cap"


# ----------------------------------------------------------- stall_untested label


def test_stall_untested_is_in_the_ledger_and_the_chief_tables(spec, tmp_path):
    untested, probed, nf = rec(wp(8.0), -1.40), rec(wp(8.5), -1.50, stall=_probe(False, 0.02)), nf_rec(wp(9.0), -1.5)
    assert untested.stall_untested and not probed.stall_untested and not nf.stall_untested
    files = RunFiles(tmp_path / "l")
    for r in (untested, probed, nf):
        files.append_record(r)
    raw = [json.loads(x) for x in files.ledger.read_text().splitlines()]
    assert [x["stall_untested"] for x in raw] == [True, False, False]
    assert [r.stall_untested for r in files.read_ledger()] == [True, False, False]  # reloads cleanly
    assert [row(r, spec)["stall_probe"] for r in (untested, probed, nf)] == ["untested", "fail", ""]
    b = chief_brief({"spec": spec, "ledger": [untested, probed], "generation": 3, "strategy": None}, {})
    assert "| stall_probe |" in b.user and "| untested |" in b.user
