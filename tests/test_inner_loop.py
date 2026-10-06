"""Hybrid inner optimizer (milestone 4), offline: NeuralFoil, scripted/mock LLM, fake XFoil, fixed seeds."""

import json

import pytest

from swarm.agents.chief import sanitize
from swarm.briefs import chief_brief
from swarm.ledger import RunFiles
from swarm.llm.client import ScriptedClient, TraceLogger
from swarm.llm.mock import MockClient
from swarm.optim.inner_loop import in_region, run_inner, search_box
from swarm.optim.summary import INNER_BUDGET_DEFAULT, INNER_BUDGET_MAX, clamp_budget
from swarm.run import run
from swarm.solvers import neuralfoil
from swarm.state import Diagnosis, EvalRecord, StrategyMemo, Verdict, WingParams, free_params

PARENT = WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.13, alpha_deg=6.0)


def memo(focus, mode="inner_optimizer", radius=0.15, k=6, fidelity="neuralfoil", **kw):
    return StrategyMemo(
        hypothesis="h", focus_params=focus, trust_radius=radius, fidelity=fidelity, mode=mode, inner_budget=k, **kw
    )


def verdict():
    return Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="NONE"), confidence=0.6)


def nf_record(p: WingParams, spec, gen=0) -> EvalRecord:
    from swarm.baselines import record_evaluation

    rec, _ = record_evaluation(gen, p, neuralfoil.evaluate(p, spec), spec, [], "seed", "/tmp")
    return rec


def events(d):
    return [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()]


# ----------------------------------------------------------- search space


def test_search_box_is_the_trust_region_on_focus_params_one_sided_by_direction(spec):
    m = memo([{"name": "alpha_deg", "direction": "+"}, {"name": "main_camber", "direction": "-"}, "main_thickness"])
    box = search_box(PARENT, m, spec)
    assert set(box) == {"alpha_deg", "main_camber", "main_thickness"}  # focus only: camber_pos stays put
    assert box["alpha_deg"] == pytest.approx((6.0, 6.0 + 0.15 * 16))
    assert box["main_camber"] == pytest.approx((0.06 - 0.15 * 0.09, 0.06))
    assert box["main_thickness"] == pytest.approx((0.13 - 0.015, 0.13 + 0.015))
    at_top = PARENT.model_copy(update={"main_camber": 0.09})
    assert "main_camber" not in search_box(at_top, memo([{"name": "main_camber", "direction": "+"}]), spec)


def test_inner_run_is_deterministic_stays_in_the_box_and_records_every_evaluation(spec, tmp_path):
    m = memo(["alpha_deg", "main_camber"], k=5)
    a = run_inner(PARENT, m, spec, [], gen=3, run_dir=str(tmp_path), budget=5)
    b = run_inner(PARENT, m, spec, [], gen=3, run_dir=str(tmp_path), budget=5)
    assert [r.params.cid for r in a.records] == [r.params.cid for r in b.records]
    assert len(a.records) == 5 and len({r.params.cid for r in a.records}) == 5
    box = search_box(PARENT, m, spec)
    for r in a.records:
        assert r.inner_optimizer and r.generation == 3 and r.parent_cid == PARENT.cid
        assert r.result.fidelity == "neuralfoil" and r.verdict is not None
        assert r.params.main_thickness == PARENT.main_thickness and r.params.main_camber_pos == PARENT.main_camber_pos
        assert all(box[n][0] - 1e-9 <= getattr(r.params, n) <= box[n][1] + 1e-9 for n in box)
        assert r.screen is not None or r.verdict.status != "TARGET_MISS"  # same screen as the agents' path
    kinds = [e["event"] for e in a.events]
    assert kinds[0] == "inner_optimizer_started" and kinds[-1] == "inner_optimizer_finished"
    assert kinds.count("inner_trial") == 5
    assert a.summary["evals"] == 5 and a.summary["best"]["cid"] in {r.params.cid for r in a.records}
    other = run_inner(PARENT, m, spec, [], gen=4, run_dir=str(tmp_path), budget=5)  # another generation, another seed
    assert [r.params.cid for r in other.records] != [r.params.cid for r in a.records]


def test_warm_start_uses_neuralfoil_records_in_the_region_only(spec, tmp_path):
    m = memo(["alpha_deg"], radius=0.1, k=3)
    inside = nf_record(PARENT.model_copy(update={"alpha_deg": 6.8}), spec)
    off_axis = nf_record(PARENT.model_copy(update={"alpha_deg": 6.4, "main_camber": 0.08}), spec)  # camber too far
    far = nf_record(PARENT.model_copy(update={"alpha_deg": 12.0}), spec)
    xfoil = inside.model_copy(update={"result": inside.result.model_copy(update={"fidelity": "xfoil"})})
    box = search_box(PARENT, m, spec)
    assert in_region(inside.params, PARENT, box, 0.1, spec) and not in_region(far.params, PARENT, box, 0.1, spec)
    assert not in_region(off_axis.params, PARENT, box, 0.1, spec)
    out = run_inner(PARENT, m, spec, [inside, off_axis, far, xfoil], gen=1, run_dir=str(tmp_path), budget=3)
    assert out.summary["warm_trials"] == 1


def test_repeats_and_an_exhausted_box_cost_no_evaluation(spec, tmp_path):
    # camber +/- 0.02 of its range around the parent is within the near-duplicate tolerance of the parent
    parent = nf_record(PARENT, spec)
    out = run_inner(PARENT, memo(["main_camber"], radius=0.02), spec, [parent], 1, str(tmp_path), budget=4)
    assert out.records == [] and out.summary["evals"] == 0 and out.summary["repeats"] > 0
    assert out.summary["stopped"].startswith("no new feasible design in the box")


# ----------------------------------------------------------- Chief sanitize


def test_sanitize_inner_mode(spec):
    st = {"spec": spec, "ledger": [], "generation": 2, "inner_allowed": True}
    m, ev = sanitize(memo(["alpha_deg"], k=0, fidelity="xfoil"), st)
    assert m.mode == "inner_optimizer" and m.inner_budget == INNER_BUDGET_DEFAULT and m.fidelity == "neuralfoil"
    assert {e["event"] for e in ev} == {"inner_budget_coerced", "inner_optimizer_fidelity"}
    m, _ = sanitize(memo(["alpha_deg"], k=99), st)
    assert m.inner_budget == INNER_BUDGET_MAX == clamp_budget(99)
    m, ev = sanitize(memo(["alpha_deg"]), {**st, "inner_allowed": False})
    assert m.mode == "reasoned_step" and m.inner_budget == 0 and ev[0]["event"] == "inner_optimizer_unavailable"
    m, ev = sanitize(memo(["alpha_deg"]), {k: v for k, v in st.items() if k != "inner_allowed"})
    assert m.mode == "reasoned_step"  # not enabled unless the run says so
    m, _ = sanitize(memo(["alpha_deg"], mode="reasoned_step", k=5), st)
    assert m.inner_budget == 0


def test_a_promotion_takes_precedence_over_an_inner_run(spec):
    rec = nf_record(PARENT, spec)
    rec = rec.model_copy(update={"screen": rec.screen.model_copy(update={"ok": True})})
    st = {"spec": spec, "ledger": [rec], "generation": 2, "inner_allowed": True}
    m, ev = sanitize(memo(["alpha_deg"], fidelity="xfoil", promote_cid=PARENT.cid), st)
    assert m.mode == "reasoned_step" and m.promote_cid == PARENT.cid and m.fidelity == "xfoil"
    assert ev[-1]["event"] == "inner_optimizer_deferred"


def test_prompt_and_brief_state_whether_the_mode_is_available(spec):
    on = chief_brief({"spec": spec, "ledger": [], "inner_allowed": True}, {})
    off = chief_brief({"spec": spec, "ledger": [], "inner_allowed": False}, {})
    assert '"reasoned_step" or "inner_optimizer"' in on.system and "Optuna TPE, no LLM" in on.system
    assert "inner optimizer is disabled in this run" in off.system and "Optuna" not in off.system
    assert "## Inner-optimizer runs" in on.user and "(none yet)" in on.user
    assert "(disabled in this run)" in off.user
    assert on.facts["inner_optimizer"]["allowed"] and not off.facts["inner_optimizer"]["allowed"]


# ----------------------------------------------------------- in the graph


def test_graph_inner_run_counts_toward_the_budget_and_reaches_the_next_brief(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    m0 = memo(list(free_params(spec))[:3], mode="reasoned_step", k=0)
    m1 = memo(["alpha_deg", "main_camber"], k=4)
    # gen 0 baseline; gen 1 inner run (no CAD, no Critic); gen 2 another inner run, clipped to 1 evaluation
    llm = ScriptedClient([m0, verdict(), m1, m1])
    s = spec.model_copy(update={"max_evals": 6})
    final = run(s, start, run_id="h", runs_root=tmp_path, llm=llm)
    assert len(final["ledger"]) == 6 and final["termination"] == "eval_budget"
    inner = [r for r in final["ledger"] if r.inner_optimizer]
    assert len(inner) == 5 and [r.generation for r in inner] == [1, 1, 1, 1, 2]
    assert [c["role"] for c in llm.calls] == ["chief", "critic", "chief", "chief"]  # no LLM inside the loop
    brief = llm.calls[-1]["user"]
    assert "## Inner-optimizer runs" in brief and "- gen 1: TPE over alpha_deg [" in brief
    assert "- gen 1: h -> inner optimizer: TPE over" in brief  # history outcome
    assert "| inner |" in brief  # Last 5 marks inner records
    d = tmp_path / "h"
    ev = events(d)
    assert [e["event"] for e in ev if e.get("node") == "inner_optimize"].count("inner_trial") == 5
    ledger = RunFiles(d).read_ledger()
    assert len(ledger) == 6 and sum(r.inner_optimizer for r in ledger) == 5
    report = (d / "report.md").read_text()
    assert "## Inner-optimizer runs" in report and "2 run(s), 5 ledger evaluation(s)" in report
    meta = json.loads((d / "meta.json").read_text())
    assert meta["inner_optimizer"] is True


def test_inner_run_is_clipped_to_the_remaining_budget(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    llm = ScriptedClient([memo(["alpha_deg"], mode="reasoned_step", k=0), verdict(), memo(["alpha_deg"], k=8)])
    final = run(spec.model_copy(update={"max_evals": 3}), start, run_id="c", runs_root=tmp_path, llm=llm)
    assert len(final["ledger"]) == 3 and final["termination"] == "eval_budget"
    fin = [e for e in events(tmp_path / "c") if e.get("event") == "inner_optimizer_finished"]
    assert fin[0]["budget"] == 2 and fin[0]["evals"] == 2


def test_llm_only_run_coerces_the_mode_and_calls_the_cad(spec, start, fake_xfoil, tmp_path):
    from swarm.state import ParamChange, ParamDelta

    fake_xfoil()
    ch = ParamChange(name="alpha_deg", new_value=7.0, mechanism="m", expected_dCl_sign=-1, expected_dCd_sign=1)
    script = [memo(["alpha_deg"], mode="reasoned_step", k=0), verdict(), memo(["alpha_deg"]), ParamDelta(changes=[ch])]
    script.append(verdict())
    llm = ScriptedClient(script)
    final = run(
        spec.model_copy(update={"max_evals": 2}), start, run_id="l", runs_root=tmp_path, llm=llm, inner_optimizer=False
    )
    assert not llm.responses and not any(r.inner_optimizer for r in final["ledger"])
    assert any(e.get("event") == "inner_optimizer_unavailable" for e in events(tmp_path / "l"))
    assert "inner optimizer is disabled in this run" in llm.calls[0]["system"]


def test_empty_inner_run_falls_back_to_a_cad_step(spec, start, fake_xfoil, tmp_path):
    from swarm.state import ParamChange, ParamDelta

    fake_xfoil()
    top = start.model_copy(update={"main_camber": 0.09})
    ch = ParamChange(name="main_camber", new_value=0.085, mechanism="m", expected_dCl_sign=1, expected_dCd_sign=-1)
    script = [
        memo(["main_camber"], mode="reasoned_step", k=0),
        verdict(),
        memo([{"name": "main_camber", "direction": "+"}]),  # no room above the bound: empty box
        ParamDelta(changes=[ch.model_copy(update={"override_reason": "no room to increase"})]),
        verdict(),
    ]
    llm = ScriptedClient(script)
    final = run(spec.model_copy(update={"max_evals": 2}), top, run_id="e", runs_root=tmp_path, llm=llm)
    assert not llm.responses and len(final["ledger"]) == 2
    ev = events(tmp_path / "e")
    assert any(e.get("event") == "inner_optimizer_empty" for e in ev)
    assert [c["role"] for c in llm.calls] == ["chief", "critic", "chief", "cad", "critic"]


def test_mock_hybrid_run_is_deterministic(spec, start, fake_xfoil, tmp_path):
    fake_xfoil(flat_probes=True)  # nothing passes at XFoil: the run uses its whole budget
    s = spec.model_copy(update={"max_evals": 14})

    def go(rid):
        files = RunFiles(tmp_path / rid)
        llm = MockClient(TraceLogger(files.traces), inner_budget=4)
        return run(s, start, run_id=rid, runs_root=tmp_path, llm=llm)

    a, b = go("a"), go("b")
    assert [r.params.cid for r in a["ledger"]] == [r.params.cid for r in b["ledger"]]
    assert any(r.inner_optimizer for r in a["ledger"])
