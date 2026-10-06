"""Hybrid inner optimizer (milestone 4), offline: NeuralFoil, scripted/mock LLM, fake XFoil, fixed seeds."""

import json

import pytest

from swarm.agents.chief import sanitize
from swarm.briefs import chief_brief
from swarm.critic.screen import surrogate_screen
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
    assert box["main_thickness"] == pytest.approx((0.123, 0.13 + 0.015))  # 0.115 raised to the FSAE minimum
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
    screened = [r for r in a.records if r.verdict.status in ("PASS", "TARGET_MISS")]
    assert screened and all(r.screen is not None for r in screened)
    assert screened[0].screen == surrogate_screen(screened[0].params, spec)  # the screen the graph path uses
    kinds = [e["event"] for e in a.events]
    assert kinds[0] == "inner_optimizer_started" and kinds[-1] == "inner_optimizer_finished"
    assert kinds.count("inner_trial") == 5
    assert a.summary["evals"] == 5 and a.summary["best"]["cid"] in {r.params.cid for r in a.records}
    other = run_inner(PARENT, m, spec, [], gen=4, run_dir=str(tmp_path), budget=5)  # another generation, another seed
    assert [r.params.cid for r in other.records] != [r.params.cid for r in a.records]


def test_warm_start_uses_neuralfoil_records_in_the_searched_subspace_only(spec, tmp_path):
    m = memo(["alpha_deg"], radius=0.1, k=3)
    inside = nf_record(PARENT.model_copy(update={"alpha_deg": 6.8}), spec)
    # within the trust radius, but camber differs from the parent's: TPE would read it at the parent's camber
    off_axis = nf_record(PARENT.model_copy(update={"alpha_deg": 6.4, "main_camber": 0.065}), spec)
    far = nf_record(PARENT.model_copy(update={"alpha_deg": 12.0}), spec)
    xfoil = inside.model_copy(update={"result": inside.result.model_copy(update={"fidelity": "xfoil"})})
    box = search_box(PARENT, m, spec)
    assert in_region(inside.params, PARENT, box, spec) and not in_region(far.params, PARENT, box, spec)
    assert not in_region(off_axis.params, PARENT, box, spec)
    out = run_inner(PARENT, m, spec, [inside, off_axis, far, xfoil], gen=1, run_dir=str(tmp_path), budget=3)
    assert out.summary["warm_trials"] == 1


def test_warm_start_on_the_trust_region_edge_does_not_crash(spec, tmp_path):
    """Regression (session 13 review): 6.0 - 0.3*16 is 1.2000000000000002 in floats; a record at alpha 1.2
    passed the region check but Optuna's distribution rejected it (11 crashed inner runs in bench4)."""
    m = memo(["alpha_deg"], radius=0.3, k=2)
    edge = nf_record(PARENT.model_copy(update={"alpha_deg": 1.2}), spec)
    box = search_box(PARENT, m, spec)
    assert box["alpha_deg"] == (1.2, 10.8) and in_region(edge.params, PARENT, box, spec)
    out = run_inner(PARENT, m, spec, [edge], gen=1, run_dir=str(tmp_path), budget=2)
    assert out.summary["warm_trials"] == 1 and len(out.records) == 2


def test_box_is_on_the_grid_and_respects_the_rulebook_thickness(spec, tmp_path):
    m = memo(["main_thickness", "alpha_deg"], radius=0.123, k=4)
    box = search_box(PARENT, m, spec)
    assert box["main_thickness"][0] == 0.123  # FSAE T.7.1.4: 5 mm LE radius on 300 mm (0.12298 rounded up)
    assert all(round(v, 4) == v for lohi in box.values() for v in lohi)
    out = run_inner(PARENT, m, spec, [], gen=2, run_dir=str(tmp_path), budget=4)
    assert out.summary["rejected_geometry"] == 0
    for r in out.records:
        assert all(box[n][0] <= getattr(r.params, n) <= box[n][1] for n in box)


def test_an_error_mid_run_keeps_the_records_made_so_far(spec, tmp_path, monkeypatch):
    real, calls = neuralfoil.evaluate, []

    def flaky(p, s, **kw):
        calls.append(p.cid)
        if len(calls) == 3:
            raise RuntimeError("solver crashed")
        return real(p, s, **kw)

    monkeypatch.setattr("swarm.optim.inner_loop.neuralfoil.evaluate", flaky)
    out = run_inner(PARENT, memo(["alpha_deg", "main_camber"]), spec, [], gen=1, run_dir=str(tmp_path), budget=5)
    assert len(out.records) == 2 and out.summary["evals"] == 2
    assert out.summary["stopped"].startswith("error: RuntimeError('solver crashed')")
    assert any(e["event"] == "inner_optimizer_error" for e in out.events)


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
    m, ev = sanitize(memo(["alpha_deg"], mode="reasoned_step", k=5), st)
    assert m.inner_budget == 0 and ev[-1]["event"] == "inner_budget_ignored"
    last = {**st, "ledger": [nf_record(PARENT, spec)] * (spec.max_evals - 1)}
    m, ev = sanitize(memo(["alpha_deg"]), last)  # the run's last evaluation: no inner run
    assert m.mode == "reasoned_step" and ev[-1]["detail"] == "1 evaluation(s) left"


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
    assert "Inner-optimizer runs" not in off.user and "inner-optimizer" not in off.system
    assert on.facts["inner_optimizer"]["allowed"] and not off.facts["inner_optimizer"]["allowed"]


# ----------------------------------------------------------- in the graph


def test_graph_inner_run_counts_toward_the_budget_and_reaches_the_next_brief(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    m0 = memo(list(free_params(spec))[:3], mode="reasoned_step", k=0)
    m1 = memo(["alpha_deg", "main_camber"], k=4)
    stop = memo(["alpha_deg"], mode="reasoned_step", k=0, declare_plateau=True)
    # gen 0 baseline; gen 1 inner run (no CAD, no Critic); gen 2 inner run clipped to 1 evaluation (the 7th
    # is kept for a promotion); gen 3 declares a plateau (allowed after 6 of 7)
    llm = ScriptedClient([m0, verdict(), m1, m1, stop])
    s = spec.model_copy(update={"max_evals": 7})
    final = run(s, start, run_id="h", runs_root=tmp_path, llm=llm)
    assert len(final["ledger"]) == 6 and final["termination"] == "plateau" and not llm.responses
    inner = [r for r in final["ledger"] if r.inner_optimizer]
    assert [r.generation for r in inner] == [1, 1, 1, 1, 2]
    assert [c["role"] for c in llm.calls] == ["chief", "critic", "chief", "chief", "chief"]  # no LLM in the loop
    brief = llm.calls[-1]["user"]
    assert "## Inner-optimizer runs" in brief and "- gen 1: TPE over alpha_deg [" in brief
    assert "- gen 1: h -> inner optimizer: TPE over" in brief  # history outcome
    assert "| inner |" in brief  # Last 5 marks inner records
    d = tmp_path / "h"
    ev = events(d)
    assert [e["event"] for e in ev if e.get("node") == "inner_optimize"].count("inner_trial") == 5
    fin = [e for e in ev if e.get("event") == "inner_optimizer_finished"]
    assert [(e["budget"], e["evals"]) for e in fin] == [(4, 4), (1, 1)]
    ledger = RunFiles(d).read_ledger()
    assert len(ledger) == 6 and sum(r.inner_optimizer for r in ledger) == 5
    report = (d / "report.md").read_text()
    assert "## Inner-optimizer runs" in report and "2 run(s), 5 ledger evaluation(s)" in report
    meta = json.loads((d / "meta.json").read_text())
    assert meta["inner_optimizer"] is True


def test_inner_run_leaves_the_last_evaluation_for_a_promotion(spec, start, fake_xfoil, tmp_path):
    from swarm.state import ParamChange, ParamDelta

    fake_xfoil()
    ch = ParamChange(name="alpha_deg", new_value=4.5, mechanism="m", expected_dCl_sign=-1, expected_dCd_sign=1)
    script = [memo(["alpha_deg"], mode="reasoned_step", k=0), verdict(), memo(["alpha_deg"], k=8)]
    script += [memo(["alpha_deg"], k=8), ParamDelta(changes=[ch]), verdict()]
    llm = ScriptedClient(script)
    final = run(spec.model_copy(update={"max_evals": 4}), start, run_id="c", runs_root=tmp_path, llm=llm)
    assert len(final["ledger"]) == 4 and final["termination"] == "eval_budget" and not llm.responses
    ev = events(tmp_path / "c")
    fin = [e for e in ev if e.get("event") == "inner_optimizer_finished"]
    assert [(e["budget"], e["evals"]) for e in fin] == [(2, 2)]
    # the last evaluation: the Chief's inner choice becomes a reasoned CAD step
    assert any(e.get("event") == "inner_optimizer_unavailable" and e["gen"] == 2 for e in ev)
    assert not final["ledger"][-1].inner_optimizer


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
        memo(["main_camber"], mode="reasoned_step", k=0),
        ParamDelta(changes=[ch.model_copy(update={"new_value": 0.08})]),
        verdict(),
    ]
    llm = ScriptedClient(script)
    final = run(spec.model_copy(update={"max_evals": 3}), top, run_id="e", runs_root=tmp_path, llm=llm)
    assert not llm.responses and len(final["ledger"]) == 3
    ev = events(tmp_path / "e")
    assert any(e.get("event") == "inner_optimizer_empty" for e in ev)
    assert [c["role"] for c in llm.calls][:5] == ["chief", "critic", "chief", "cad", "critic"]


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


def test_a_failed_chief_call_never_reuses_an_inner_run(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    # gen 0 baseline; gen 1 inner run (3 evals); then the script runs out: every later call fails
    llm = ScriptedClient([memo(["alpha_deg"], mode="reasoned_step", k=0), verdict(), memo(["alpha_deg"], k=3)])
    final = run(spec.model_copy(update={"max_evals": 6}), start, run_id="f", runs_root=tmp_path, llm=llm)
    assert len(final["ledger"]) == 6 and sum(r.inner_optimizer for r in final["ledger"]) == 3
    ev = events(tmp_path / "f")
    assert [e.get("event") for e in ev].count("inner_optimizer_started") == 1
    assert any(e.get("event") == "llm_error_reused_strategy" for e in ev)
    assert all(e["strategy"]["mode"] == "reasoned_step" for e in ev if e.get("event") == "strategy" and e["gen"] > 1)


def test_cli_resume_refuses_the_inner_optimizer_flag(tmp_path):
    from swarm.run import main

    with pytest.raises(SystemExit):
        main(["--llm", "mock", "--resume", "x", "--no-inner-optimizer", "--runs-root", str(tmp_path)])


def test_benchmark_skips_finished_and_unfinished_run_directories(tmp_path):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent.parent / "scripts" / "benchmark.py"
    sp = importlib.util.spec_from_file_location("bench", path)
    bench = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(bench)
    done = tmp_path / "llm_s11"
    done.mkdir()
    (done / "meta.json").write_text(json.dumps({"termination": "target_met"}))
    assert "already finished, skipped" in bench.one(("llm", 11, str(tmp_path)))[0]
    partial = tmp_path / "hybrid_s11"
    partial.mkdir()
    (partial / "ledger.jsonl").write_text("{}\n")
    assert "unfinished run directory" in bench.one(("hybrid", 11, str(tmp_path)))[0]


def test_benchmark_stops_the_batch_on_an_api_account_error(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent.parent / "scripts" / "benchmark.py"
    sp = importlib.util.spec_from_file_location("bench2", path)
    bench = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(bench)
    d = tmp_path / "r"
    d.mkdir()
    fail = {"type": "llm_failure", "error": "BadRequestError: Your credit balance is too low to access the API"}
    (d / "traces.jsonl").write_text(json.dumps({"type": "llm_call", "ok": True}) + "\n" + json.dumps(fail) + "\n")
    assert "credit balance is too low" in bench.account_error(d)
    (d / "traces.jsonl").write_text(json.dumps({"type": "llm_failure", "error": "APITimeoutError: timed out"}))
    assert bench.account_error(d) is None  # transient: not a reason to stop the batch
    calls = []

    def fake_one(job):
        calls.append(job)
        return f"{job[0]}_s{job[1]}: invalid_llm", "credit balance is too low"

    monkeypatch.setattr(bench, "one", fake_one)
    with pytest.raises(SystemExit) as e:
        bench.cmd_run(["hybrid"], [11, 22, 33], parallel=1, root=str(tmp_path))
    assert e.value.code == 2 and calls == [("hybrid", 11, str(tmp_path))]
