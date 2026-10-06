"""Chief brief: every design evaluated at XFoil, NeuralFoil vs XFoil, from the ledger (session 13)."""

import pytest

from swarm.briefs import chief_brief, xfoil_record, xfoil_record_text
from swarm.state import BoundaryLayerSummary, CFDResult, Diagnosis, EvalRecord, Verdict, WingParams


def rec(p, cl, fid, gen, cd=0.02, inner=False, status="TARGET_MISS"):
    r = CFDResult(
        cid=p.cid, fidelity=fid, status="converged", cl=cl, cd=cd, bl=BoundaryLayerSummary() if fid == "xfoil" else None
    )
    v = Verdict(status=status, diagnosis=Diagnosis(symptom="NONE"), confidence=0.6)
    return EvalRecord(generation=gen, params=p, result=r, verdict=v, rationale="", inner_optimizer=inner)


def test_record_lists_route_neuralfoil_vs_xfoil_and_outcome(spec):
    a = WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=6.0)
    b = a.model_copy(update={"alpha_deg": 7.0})
    ledger = [
        rec(a, -1.51, "neuralfoil", 1, inner=True),
        rec(b, -1.56, "neuralfoil", 1, inner=True),
        rec(a, -1.47, "xfoil", 2),  # overridden, in the box at NeuralFoil, under-loaded at XFoil
        rec(b, -1.555, "xfoil", 3),  # screen passed, outside the box already at NeuralFoil
    ]
    events = [{"event": "promotion_screen_override", "gen": 2, "cid": a.cid}]
    rows = xfoil_record({"spec": spec, "ledger": ledger, "events": events})
    assert [(r["cid"], r["found_by"], r["route"], r["nf_in_box"]) for r in rows] == [
        (a.cid, "inner", "screen override", "yes"),
        (b.cid, "inner", "screen passed", "no"),
    ]
    assert rows[0]["dcl"] == pytest.approx(0.04) and rows[1]["dcl"] == pytest.approx(0.005)
    assert rows[0]["outcome"].startswith("target box: Cl -1.4700")
    text = xfoil_record_text(rows)
    assert "screen override: 1 evaluated at XFoil (1 with NeuralFoil Cl inside the box), 0 passed" in text
    assert "screen passed: 1 evaluated at XFoil (0 with NeuralFoil Cl inside the box), 0 passed" in text
    assert "mean +0.0225, range +0.0050 to +0.0400 over 2 design(s)" in text
    brief = chief_brief({"spec": spec, "ledger": ledger, "events": events}, {})
    assert "## Every design evaluated at XFoil: NeuralFoil vs XFoil (ledger numbers)" in brief.user
    assert brief.facts["xfoil_record"] == rows


def test_record_is_empty_before_any_xfoil_result(spec):
    assert xfoil_record_text(xfoil_record({"spec": spec, "ledger": [], "events": []})) == "(none yet)"
