"""Live-run caps: --max-evals and --budget-usd (estimated LLM cost)."""

import json

import pytest

from swarm.llm.client import TraceLogger
from swarm.llm.mock import MockClient
from swarm.run import main, run

PER_CALL = (5000 * 4.0 + 1000 * 20.0) / 1e6  # claude-opus-5-5 prices in PRICES: $0.04 per call


class PricedTrace(TraceLogger):
    """Logs every call as if it were a priced model call (the mock itself costs nothing)."""

    def __init__(self, path, model="claude-opus-5-5"):
        super().__init__(path)
        self.model = model

    def log(self, **kw):
        kw["model"] = self.model
        kw["usage"] = {"input_tokens": 5000, "output_tokens": 1000}
        super().log(**kw)


def priced_mock(tmp_path, run_id, model="claude-opus-5-5"):
    return MockClient(PricedTrace(tmp_path / run_id / "traces.jsonl", model))


def _events(d):
    return [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()]


def test_over_budget_rules():
    t = TraceLogger(None)
    assert not t.over_budget(None) and not t.over_budget(0.01)
    t.log(
        role="r",
        client="c",
        model="claude-opus-5-5",
        schema="S",
        system="",
        user="",
        output=None,
        usage={"input_tokens": 5000, "output_tokens": 1000},
        latency_s=0.0,
    )
    assert t.totals["cost_usd"] == pytest.approx(PER_CALL)
    assert not t.over_budget(0.05) and t.over_budget(0.04) and t.over_budget(0.01)
    t.log(
        role="r",
        client="c",
        model="some-unpriced-model",
        schema="S",
        system="",
        user="",
        output=None,
        usage={"input_tokens": 1},
        latency_s=0.0,
    )
    assert t.over_budget(100.0)  # unknown spend is never assumed to be zero
    assert not t.over_budget(None)


def test_cost_cap_stops_run_cleanly(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    cap = 0.10  # crosses on the 3rd call (0.12)
    s = spec.model_copy(update={"max_cost_usd": cap})
    llm = priced_mock(tmp_path, "cap")
    final = run(s, start, run_id="cap", runs_root=tmp_path, llm=llm)
    d = tmp_path / "cap"
    assert final["termination"] == "cost_cap"
    t = llm.trace.totals
    assert t["calls"] == 3 and t["cost_usd"] == pytest.approx(3 * PER_CALL)
    assert t["cost_usd"] - cap < PER_CALL + 1e-9  # overshoot bounded by the call that crossed the cap
    # every completed evaluation is in the ledger with a verdict; the cap ends at a clean boundary
    ledger = [json.loads(x) for x in (d / "ledger.jsonl").read_text().splitlines()]
    assert len(ledger) == len(final["ledger"]) >= 1 and all(r["verdict"] for r in ledger)
    ev = _events(d)
    assert any(e.get("event") == "cost_cap_reached" for e in ev)
    assert ev[-1]["event"] == "terminated" and ev[-1]["reason"] == "cost_cap"
    meta = json.loads((d / "meta.json").read_text())
    assert meta["termination"] == "cost_cap" and meta["llm_usage"]["cost_usd"] == pytest.approx(3 * PER_CALL)
    rep = (d / "report.md").read_text()
    assert "Termination: **cost_cap**" in rep and "(cap $0.10)" in rep


def test_cost_cap_in_flight_candidate_gets_numeric_verdict(spec, start, fake_xfoil, tmp_path):
    """Cap crosses on the CAD call: the proposal is still solved and recorded,
    the Critic makes no LLM call, then the run reports."""
    fake_xfoil()
    # calls: chief(1) critic(2) chief(3) cad(4) → cap 0.15 crosses at call 4
    s = spec.model_copy(update={"max_cost_usd": 0.15})
    llm = priced_mock(tmp_path, "cap2")
    final = run(s, start, run_id="cap2", runs_root=tmp_path, llm=llm)
    assert final["termination"] == "cost_cap" and llm.trace.totals["calls"] == 4
    assert len(final["ledger"]) == 2 and final["ledger"][-1].verdict.confidence == 0.3  # numeric verdict
    ev = _events(tmp_path / "cap2")
    assert any(e.get("event") == "cost_cap_reached" and e["node"] == "critic" for e in ev)


def test_unpriced_model_with_cap_stops(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    s = spec.model_copy(update={"max_cost_usd": 100.0})
    llm = priced_mock(tmp_path, "unk", model="unknown-model")
    final = run(s, start, run_id="unk", runs_root=tmp_path, llm=llm)
    assert final["termination"] == "cost_cap" and llm.trace.totals["calls"] == 1


def test_no_cap_mock_run_unaffected(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    final = run(spec, start, run_id="free", runs_root=tmp_path, llm=priced_mock(tmp_path, "free"))
    assert final["termination"] == "target_met"


def test_trace_totals_survive_resume(tmp_path):
    p = tmp_path / "traces.jsonl"
    t = TraceLogger(p)
    for _ in range(2):
        t.log(
            role="r",
            client="c",
            model="claude-opus-5-5",
            schema="S",
            system="",
            user="",
            output=None,
            usage={"input_tokens": 5000, "output_tokens": 1000},
            latency_s=0.0,
        )
    t.write_summary()
    with p.open("a") as f:
        f.write('{"type": "llm_call", "usage": {"input_tok')  # torn line from a crash
    again = TraceLogger(p)
    assert again.totals["calls"] == 2 and again.totals["cost_usd"] == pytest.approx(2 * PER_CALL)
    assert again.over_budget(0.08)


def test_cli_budget_flag(tmp_path, fake_xfoil):
    fake_xfoil()
    main(["--llm", "mock", "--budget-usd", "1.5", "--max-evals", "3", "--runs-root", str(tmp_path), "--run-id", "b"])
    meta = json.loads((tmp_path / "b" / "meta.json").read_text())
    assert meta["spec"]["max_cost_usd"] == 1.5 and meta["spec"]["max_evals"] == 3
    assert meta["termination"] in ("budget", "target_met") and meta["evals"] <= 3


@pytest.mark.parametrize(
    "argv",
    [["--budget-usd", "0"], ["--budget-usd", "-1"], ["--max-evals", "0"], ["--resume", "x", "--budget-usd", "2"]],
)
def test_cli_rejects_bad_caps(argv):
    with pytest.raises(SystemExit):
        main(["--llm", "mock", *argv])


def test_real_llm_without_cap_warns(spec, start, fake_xfoil, tmp_path, capsys):
    fake_xfoil()

    class Real(MockClient):
        is_mock = False
        kind = "anthropic"

    s = spec.model_copy(update={"max_evals": 1})
    run(s, start, run_id="w", runs_root=tmp_path, llm=Real(TraceLogger(None)))
    assert "without a cost cap" in capsys.readouterr().err
