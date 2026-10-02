"""NeuralFoil screen: stall margin (alpha+1, +2) and suction-side separation warning.

It blocks promotion to XFoil, never overrides an XFoil result, and its disagreements with
XFoil are logged. Offline: NeuralFoil (bundled weights) and the NeuralFoil-backed fake XFoil.
"""

import json

import numpy as np
import pytest

from swarm.agents.chief import sanitize
from swarm.briefs import chief_brief, promotable
from swarm.critic import screen as screen_mod
from swarm.critic.numeric import VALIDATION, validate
from swarm.critic.screen import compare_with_xfoil, surrogate_screen
from swarm.run import HARD_SPEC, run
from swarm.state import (
    BoundaryLayerSummary,
    CFDResult,
    Diagnosis,
    EvalRecord,
    StallMargin,
    StrategyMemo,
    SurrogateScreen,
    Verdict,
    WingParams,
)

# Round 7 of the first live run (01ee6bd07c): XFoil margin 0.026, TE separation from alpha+1.
NEAR_STALL = WingParams(main_camber=0.078, main_camber_pos=0.4, main_thickness=0.117, alpha_deg=9.031)
HEALTHY = WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=4.0)


def scr(stall_ok=True, sep=False, slope=0.09) -> SurrogateScreen:
    return SurrogateScreen(
        alphas_deg=[9.0, 10.0, 11.0],
        cls=[-1.5, -1.5 - slope, -1.5 - 2 * slope],
        slopes=[slope, slope],
        dcl_dalpha=slope,
        stall_threshold=0.05,
        stall_ok=stall_ok,
        te_shape_factor=[5.0 if sep else 2.5, 3.0, 3.5],
        sep_xc=0.95 if sep else None,
        h_sep=4.25,
        sep_warning=sep,
        ok=stall_ok and not sep,
    )


def nf_rec(p, cl, cd=0.017, screen=None, gen=1, status="PASS"):
    r = CFDResult(cid=p.cid, fidelity="neuralfoil", status="converged", cl=cl, cd=cd, confidence=0.95)
    v = Verdict(status=status, diagnosis=Diagnosis(symptom="NONE"), confidence=0.7)
    return EvalRecord(generation=gen, params=p, result=r, verdict=v, rationale="", screen=screen)


# ----------------------------------------------------------- the screen itself


def test_screen_flags_the_live_run_near_stall_design():
    s = surrogate_screen(NEAR_STALL, HARD_SPEC)
    assert s.alphas_deg == pytest.approx([9.031, 10.031, 11.031])
    assert not s.stall_ok and s.dcl_dalpha == pytest.approx(0.030, abs=0.003)  # XFoil measured 0.026
    assert not s.sep_warning and s.te_shape_factor[0] < VALIDATION.screen_h_sep  # attached at the design alpha
    assert s.te_shape_factor[1] >= VALIDATION.screen_h_sep  # XFoil separates from alpha+1 too
    assert not s.ok and any("stall screen" in w for w in s.reasons())


def test_screen_passes_an_attached_low_alpha_design():
    s = surrogate_screen(HEALTHY, HARD_SPEC)
    assert s.ok and s.stall_ok and not s.sep_warning and s.reasons() == []
    assert s.dcl_dalpha > 0.08


def test_screen_warns_on_separated_design():
    stalled = NEAR_STALL.model_copy(update={"alpha_deg": 11.5})
    s = surrogate_screen(stalled, HARD_SPEC)
    assert s.sep_warning and s.sep_xc is not None and s.sep_xc > 0.5 and not s.ok
    assert any("separation warning" in w for w in s.reasons())


def test_te_run_start_stops_at_transition_and_low_h():
    n = len(screen_mod.BL_X)
    h = [2.0] * n
    h[-3:] = [5.0, 5.0, 5.0]
    assert screen_mod._te_run_start(h, 4.25, xtr=0.3) == pytest.approx(screen_mod.BL_X[-3])
    assert screen_mod._te_run_start(h, 4.25, xtr=0.95) == pytest.approx(screen_mod.BL_X[-2])  # laminar part ignored
    assert screen_mod._te_run_start([2.0] * n, 4.25, xtr=0.3) is None


def test_nonfinite_surrogate_output_fails_the_screen(monkeypatch):
    def polar(params, spec, alphas):
        return {"cl": np.array([-1.5, np.nan, -1.6]), "upper_h": np.full((3, 32), 2.0), "xtr_upper": np.full(3, 0.4)}

    monkeypatch.setattr("swarm.solvers.neuralfoil.polar", polar)
    s = surrogate_screen(HEALTHY, HARD_SPEC)
    assert s.dcl_dalpha is None and not s.stall_ok and s.sep_warning and not s.ok


def _fake_polar(monkeypatch, cls, h_te):
    def polar(params, spec, alphas):
        h = np.full((3, 32), 2.0)
        h[:, -1] = h_te
        return {"cl": np.array(cls), "upper_h": h, "xtr_upper": np.full(3, 0.4)}

    monkeypatch.setattr("swarm.solvers.neuralfoil.polar", polar)


def test_screen_slope_threshold_is_stricter_than_xfoils(monkeypatch):
    assert VALIDATION.screen_min_dcl_dalpha == 0.0575 > VALIDATION.stall_min_dcl_dalpha == 0.05
    _fake_polar(monkeypatch, [-1.80, -1.855, -1.91], [2.5, 3.0, 3.5])  # slope 0.055: XFoil's 0.05 would pass it
    s = surrogate_screen(HEALTHY, HARD_SPEC)
    assert not s.stall_ok and not s.probe_sep and not s.ok


def test_separation_at_a_probe_alpha_fails_the_screen(monkeypatch):
    _fake_polar(monkeypatch, [-1.80, -1.87, -1.94], [2.5, 3.2, 3.9])  # healthy slope, H 3.9 at alpha+2
    s = surrogate_screen(HEALTHY, HARD_SPEC)
    assert s.stall_ok and not s.sep_warning and s.probe_sep and not s.ok and not s.margin_ok
    assert any("alpha+1/+2" in w for w in s.reasons())
    xf = CFDResult(cid="c", fidelity="xfoil", status="converged", cl=-1.8, cd=0.02, bl=BoundaryLayerSummary())
    ok_probe = StallMargin(
        alphas_deg=[4, 5, 6], cls=[-1.8, -1.87, -1.94], levels=[0, 0, 0], dcl_dalpha=0.07, threshold=0.05, ok=True
    )
    assert compare_with_xfoil(s, xf, ok_probe)["disagree"] == ["stall"]  # screen blocks, XFoil passes


# ----------------------------------------------------------- validator: NeuralFoil only


def test_failed_screen_makes_an_in_box_neuralfoil_result_target_miss(spec):
    p = WingParams(main_camber=0.045, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=9.5)
    r = CFDResult(cid=p.cid, fidelity="neuralfoil", status="converged", cl=-1.49, cd=0.0175, confidence=0.95)
    assert validate(r, p, spec, [], screen=scr()).status == "PASS"
    rep = validate(r, p, spec, [], screen=scr(stall_ok=False, slope=0.02))
    assert rep.target_met and rep.status == "TARGET_MISS" and not rep.terminal
    chk = next(c for c in rep.checks if c.name == "neuralfoil_screen")
    assert not chk.ok and chk.severity == "suspect" and "stall screen" in chk.message


def test_screen_is_not_a_check_on_xfoil_results(spec):
    p = WingParams(main_camber=0.045, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=9.5)
    r = CFDResult(cid=p.cid, fidelity="xfoil", status="converged", cl=-1.49, cd=0.0175, solver_level=0)
    rep = validate(r, p, spec, [], screen=scr(stall_ok=False, sep=True))
    assert all(c.name != "neuralfoil_screen" for c in rep.checks)


# ----------------------------------------------------------- promotion gate


def test_promotable_excludes_screen_failures_and_brief_lists_them(spec):
    a = WingParams(main_camber=0.05, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=8.0)
    b = WingParams(main_camber=0.05, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=8.5)
    ledger = [nf_rec(a, -1.50, screen=scr()), nf_rec(b, -1.51, screen=scr(stall_ok=False, slope=0.01), gen=2)]
    assert [r.params.cid for r in promotable(ledger, spec)] == [a.cid]
    brief = chief_brief({"spec": spec, "ledger": ledger, "generation": 3}, {})
    assert brief.facts["promotable"] == [a.cid] and list(brief.facts["screen_blocked"]) == [b.cid]
    assert f"- {b.cid}: NeuralFoil stall screen" in brief.user


def test_chief_cannot_promote_a_screen_failure(spec):
    p = WingParams(main_camber=0.05, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=8.5)
    ledger = [nf_rec(p, -1.51, screen=scr(sep=True))]
    memo = StrategyMemo(
        hypothesis="h",
        focus_params=["alpha_deg"],
        trust_radius=0.1,
        fidelity="xfoil",
        mode="reasoned_step",
        promote_cid=p.cid,
    )
    out, events = sanitize(memo, {"spec": spec, "ledger": ledger, "generation": 2})
    assert out.promote_cid is None and out.fidelity == "neuralfoil"
    ev = next(e for e in events if e["event"] == "promotion_blocked_by_screen")
    assert ev["cid"] == p.cid and "separation warning" in ev["reasons"][0]
    ledger_ok = [nf_rec(p, -1.51, screen=scr())]
    out, events = sanitize(memo, {"spec": spec, "ledger": ledger_ok, "generation": 2})
    assert out.promote_cid == p.cid and out.fidelity == "xfoil" and not events


# ----------------------------------------------------------- screen vs XFoil


def test_compare_with_xfoil_reports_each_disagreement():
    r = CFDResult(cid="c", fidelity="xfoil", status="converged", cl=-1.5, cd=0.02, bl=BoundaryLayerSummary())
    bad = StallMargin(
        alphas_deg=[9, 10, 11], cls=[-1.5, -1.51, -1.52], levels=[0, 0, 0], dcl_dalpha=0.01, threshold=0.05, ok=False
    )
    assert compare_with_xfoil(scr(), r, bad)["disagree"] == ["stall"]
    assert compare_with_xfoil(scr(stall_ok=False), r, bad)["disagree"] == []
    sep = r.model_copy(update={"bl": BoundaryLayerSummary(te_separation_xc=0.9)})
    assert compare_with_xfoil(scr(), sep, None)["disagree"] == ["separation"]
    assert "stall" not in compare_with_xfoil(scr(), r, None)  # no probe, no stall comparison


def test_graph_logs_screen_xfoil_disagreement(spec, start, fake_xfoil, tmp_path):
    """The fake XFoil's probes are flat (no margin) while NeuralFoil sees a healthy lift curve."""
    fake_xfoil(flat_probes=True)
    s = spec.model_copy(update={"max_evals": 14})
    final = run(s, start, run_id="d", runs_root=tmp_path, which="mock")
    probed = [r for r in final["ledger"] if r.stall_margin is not None]
    assert probed and all(r.screen is not None and r.screen.stall_ok for r in probed)
    events = [json.loads(x) for x in (tmp_path / "d" / "events.jsonl").read_text().splitlines()]
    dis = [e for e in events if e.get("event") == "screen_xfoil_disagreement"]
    assert {e["cid"] for e in dis} == {r.params.cid for r in probed}
    assert all(e["disagree"] == ["stall"] and e["stall"]["screen_ok"] and not e["stall"]["xfoil_ok"] for e in dis)
    # every NeuralFoil record carries its screen; promoted cids all passed it
    nf = {r.params.cid: r for r in final["ledger"] if r.result.fidelity == "neuralfoil"}
    assert all(r.screen is not None for r in nf.values())
    assert all(
        nf[r.params.cid].screen.ok for r in final["ledger"] if r.result.fidelity == "xfoil" and r.params.cid in nf
    )
