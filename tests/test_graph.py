"""Graph behaviour end to end, offline: mock/scripted LLM + NeuralFoil + fake XFoil."""

import json
import time

from conftest import good_stall

from swarm.critic.numeric import validate
from swarm.graph import build_graph, checkpointer, route_after_critic_fn
from swarm.ledger import RunFiles
from swarm.llm.client import ScriptedClient, TraceLogger
from swarm.llm.mock import MockClient
from swarm.run import run
from swarm.state import (
    CFDResult,
    Diagnosis,
    ParamChange,
    ParamDelta,
    StrategyMemo,
    Verdict,
    WingParams,
)


def test_full_mock_run_hits_target(spec, start, fake_xfoil, tmp_path):
    calls = fake_xfoil()
    final = run(spec, start, run_id="t1", runs_root=tmp_path, which="mock", inject_faults=True)
    d = tmp_path / "t1"
    assert final["termination"] == "target_met"
    ledger = [json.loads(x) for x in (d / "ledger.jsonl").read_text().splitlines()]
    assert len(ledger) == len(final["ledger"]) >= 3
    assert ledger[-1]["result"]["fidelity"] == "xfoil" and calls
    meta = json.loads((d / "meta.json").read_text())
    assert meta["is_mock"] and "NOT an LLM" in meta["llm_client"] and meta["termination"] == "target_met"
    traces = [json.loads(x) for x in (d / "traces.jsonl").read_text().splitlines()]
    assert traces[-1]["type"] == "run_summary" and traces[-1]["is_mock"]
    assert all(t["client"] == "mock" for t in traces[:-1])
    assert (d / "evolution_strip.png").stat().st_size > 1000 and (d / "evolution_morph.gif").exists()
    events = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()]
    assert any(e.get("event") == "proposal_rejected" and e["error"]["kind"] == "bounds" for e in events)
    assert "Termination: **target_met**" in (d / "report.md").read_text()


def test_xfoil_ladder_in_graph(spec, start, fake_xfoil, tmp_path):
    calls = fake_xfoil(fail_levels=(0, 1))
    final = run(spec, start, run_id="t2", runs_root=tmp_path, which="mock")
    events = [json.loads(x) for x in (tmp_path / "t2" / "events.jsonl").read_text().splitlines()]
    rec = [e for e in events if e.get("event") == "xfoil_recovery"]
    assert [(e["from_level"], e["to_level"]) for e in rec[:2]] == [(0, 1), (1, 2)]
    xf = [r for r in final["ledger"] if r.result.fidelity == "xfoil"]
    assert xf and all(r.result.solver_level == 2 for r in xf)
    cid = xf[0].params.cid
    assert [c[1] for c in calls if c[0] == cid and len(c) == 2][:3] == [0, 1, 2]  # never repeats a level


def test_exhausted_ladder_falls_back_and_never_ends_as_target_met(spec, start, fake_xfoil, tmp_path):
    fake_xfoil(fail_levels=(0, 1, 2, 3))
    s = spec.model_copy(update={"max_evals": 8})
    final = run(s, start, run_id="t3", runs_root=tmp_path, which="mock")
    fb = [r for r in final["ledger"] if r.result.lower_fidelity]
    assert fb and all(r.result.fallback_from == "xfoil" for r in fb)
    assert final["termination"] != "target_met"
    events = [json.loads(x) for x in (tmp_path / "t3" / "events.jsonl").read_text().splitlines()]
    assert any(e.get("event") == "xfoil_ladder_exhausted" for e in events)


def _state(spec, verdict_status, result, terminal, n=1):
    rep = validate(result, _P, spec, [], stall=good_stall())
    assert rep.terminal == terminal
    v = Verdict(status=verdict_status, diagnosis=Diagnosis(symptom="NONE"), confidence=0.5)
    return {
        "spec": spec,
        "verdict": v,
        "result": result,
        "numeric": rep,
        "ledger": [None] * n,
        "started_at": time.time(),
    }


_P = WingParams(main_camber=0.045, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=9.5)


def test_route_after_critic(spec):
    ok = CFDResult(cid=_P.cid, fidelity="xfoil", status="converged", cl=-1.49, cd=0.0175)
    assert route_after_critic_fn(_state(spec, "PASS", ok, True)) == "report"
    fb = ok.model_copy(update={"fidelity": "neuralfoil", "fallback_from": "xfoil", "confidence": 0.95})
    assert route_after_critic_fn(_state(spec, "PASS", fb, False)) == "chief_plan"  # never target_met
    nf = ok.model_copy(update={"fidelity": "neuralfoil", "confidence": 0.95})
    assert route_after_critic_fn(_state(spec, "PASS", nf, False)) == "chief_plan"
    miss = ok.model_copy(update={"cl": -1.2})
    assert route_after_critic_fn(_state(spec, "TARGET_MISS", miss, False)) == "chief_plan"
    assert route_after_critic_fn(_state(spec, "NON_PHYSICAL", miss, False)) == "cad_propose"
    assert route_after_critic_fn(_state(spec, "UNSTEADY", miss, False)) == "cad_propose"
    assert route_after_critic_fn(_state(spec, "TARGET_MISS", miss, False, n=spec.max_evals)) == "report"


def _verdict(status="TARGET_MISS"):
    return Verdict(status=status, diagnosis=Diagnosis(symptom="INSUFFICIENT_LOADING"), confidence=0.6)


def _delta(name, value):
    return ParamDelta(
        changes=[ParamChange(name=name, new_value=value, mechanism="m", expected_dCl_sign=-1, expected_dCd_sign=1)]
    )


def test_scenario_a_violations_fed_back_then_fallback(spec, start, tmp_path):
    memo = StrategyMemo(
        hypothesis="more loading",
        focus_params=["alpha_deg", "main_thickness"],
        trust_radius=0.3,
        fidelity="neuralfoil",
        mode="reasoned_step",
    )
    script = [
        memo,
        _verdict(),  # gen 0 baseline
        memo,  # gen 1
        _delta("main_thickness", 0.25),  # bounds
        _delta("alpha_deg", 13.9),  # trust region (4 + 0.3·16 = 8.8)
        _delta("main_thickness", 0.092),  # inside trust region, but < 0.0953: FS2026 T2.4.1 at geometry
        _verdict(),
    ]  # after the deterministic fallback
    llm = ScriptedClient(script)
    s = spec.model_copy(update={"max_evals": 2})
    final = run(s, start, run_id="t4", runs_root=tmp_path, llm=llm)
    cad_calls = [c for c in llm.calls if c["role"] == "cad"]
    assert len(cad_calls) == 3
    assert "bounds: main_thickness 0.25 > max 0.18" in cad_calls[1]["user"]  # verbatim feedback
    assert "trust_region: alpha_deg 13.9" in cad_calls[2]["user"]
    events = [json.loads(x) for x in (tmp_path / "t4" / "events.jsonl").read_text().splitlines()]
    geo = [e for e in events if e.get("event") == "geometry_rejected"]
    assert geo and geo[0]["violations"][0].startswith("T2.4.1")
    assert any(e.get("event") == "cad_fallback" for e in events)
    assert final["ledger"][-1].rationale.startswith("deterministic fallback")
    assert final["termination"] == "eval_budget" and not llm.responses


def test_checkpoint_resume(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    files = RunFiles(tmp_path / "ck")
    g = build_graph(MockClient(TraceLogger(files.traces)), files, start)
    cfg = {"configurable": {"thread_id": "ck"}, "recursion_limit": 1000}
    init = {
        "spec": spec,
        "run_dir": str(files.dir),
        "generation": 0,
        "params": start,
        "ledger": [],
        "events": [],
        "retries": {},
        "started_at": time.time(),
    }
    with checkpointer(files.dir / "ckpt.db") as cp:
        s = g.compile(checkpointer=cp, interrupt_after=["critic"]).invoke(init, cfg)
        assert len(s["ledger"]) == 1
    with checkpointer(files.dir / "ckpt.db") as cp:  # a fresh process would do exactly this
        app = g.compile(checkpointer=cp)
        snap = app.get_state(cfg)
        assert snap.next == ("chief_plan",) and type(snap.values["ledger"][0]).__name__ == "EvalRecord"
        final = app.invoke(None, cfg)
    assert final["termination"] == "target_met" and final["ledger"][0].params == start
