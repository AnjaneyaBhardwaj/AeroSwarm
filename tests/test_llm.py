import json
from types import SimpleNamespace

import pytest

from swarm.llm.client import (
    AnthropicClient,
    LLMRefusal,
    ScriptedClient,
    TraceLogger,
    estimate_cost,
    make_client,
    require_real_llm,
)
from swarm.llm.mock import MockClient
from swarm.state import Diagnosis, StrategyMemo, Verdict

MEMO = StrategyMemo(
    hypothesis="h", focus_params=["alpha_deg"], trust_radius=0.1, fidelity="neuralfoil", mode="reasoned_step"
)


class FakeSDK:
    """Stands in for anthropic.Anthropic(); records the request."""

    def __init__(self, parsed, stop_reason="end_turn"):
        self.requests = []
        usage = SimpleNamespace(
            input_tokens=1200, output_tokens=300, cache_read_input_tokens=0, cache_creation_input_tokens=0
        )
        resp = SimpleNamespace(parsed_output=parsed, usage=usage, stop_reason=stop_reason, model="claude-opus-5-5")

        def parse(**kw):
            self.requests.append(kw)
            return resp

        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=parse))


def test_cost_estimate():
    assert estimate_cost("claude-opus-5-5", {"input_tokens": 1_000_000}) == pytest.approx(4.0)
    assert estimate_cost("claude-opus-5-5", {"output_tokens": 1_000_000}) == pytest.approx(20.0)
    assert estimate_cost("unknown-model", {"input_tokens": 5}) is None


def test_anthropic_client_logs_tokens_and_cost(tmp_path):
    trace = TraceLogger(tmp_path / "traces.jsonl")
    sdk = FakeSDK(MEMO)
    c = AnthropicClient(trace, sdk_client=sdk)
    out = c.structured("chief", "sys", "user text", StrategyMemo)
    assert out == MEMO and not c.is_mock
    req = sdk.requests[0]
    assert req["output_format"] is StrategyMemo and req["model"] == "claude-opus-5-5"
    assert req["thinking"] == {"type": "adaptive"}
    trace.write_summary()
    lines = [json.loads(x) for x in (tmp_path / "traces.jsonl").read_text().splitlines()]
    call, summary = lines
    assert call["usage"]["input_tokens"] == 1200 and call["cost_usd"] == pytest.approx((1200 * 4 + 300 * 20) / 1e6)
    assert call["user"] == "user text" and call["output"]["hypothesis"] == "h"
    assert summary["type"] == "run_summary" and summary["input_tokens"] == 1200
    assert summary["cost_usd"] == pytest.approx(0.0108)


def test_anthropic_refusal_raises(tmp_path):
    c = AnthropicClient(TraceLogger(None), sdk_client=FakeSDK(None, stop_reason="refusal"))
    with pytest.raises(LLMRefusal):
        c.structured("chief", "s", "u", StrategyMemo)


def test_mock_is_labelled_and_rejected_for_comparisons():
    m = MockClient(TraceLogger(None))
    assert m.is_mock and m.kind == "mock" and "NOT an LLM" in m.label
    with pytest.raises(ValueError, match="not an LLM"):
        require_real_llm(m)
    require_real_llm(AnthropicClient(TraceLogger(None), sdk_client=FakeSDK(MEMO)))


def test_mock_trace_marks_mock(tmp_path):
    trace = TraceLogger(tmp_path / "t.jsonl")
    m = MockClient(trace)
    facts = {
        "suggested_diagnosis": Diagnosis(symptom="NONE").model_dump(),
        "numeric": {"checks": []},
        "numeric_status": "TARGET_MISS",
        "result": None,
    }
    v = m.structured("critic", "s", "u", Verdict, facts=facts)
    assert v.status == "TARGET_MISS"
    rec = json.loads((tmp_path / "t.jsonl").read_text())
    assert rec["client"] == "mock" and rec["mock"] is True and rec["cost_usd"] == 0.0


def test_make_client_without_key_is_mock(monkeypatch):
    monkeypatch.delenv("AEROSWARM_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AEROSWARM_LLM", raising=False)
    assert make_client(TraceLogger(None)).is_mock


def test_make_client_ignores_sdk_default_key(monkeypatch):
    monkeypatch.delenv("AEROSWARM_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AEROSWARM_LLM", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-ours")
    assert make_client(TraceLogger(None)).is_mock


def test_make_client_with_key_is_anthropic(monkeypatch):
    monkeypatch.delenv("AEROSWARM_LLM", raising=False)
    monkeypatch.setenv("AEROSWARM_ANTHROPIC_API_KEY", "sk-ant-test")
    c = make_client(TraceLogger(None))
    assert c.kind == "anthropic" and not c.is_mock
    assert c._sdk.api_key == "sk-ant-test"


def test_anthropic_client_requires_the_key(monkeypatch):
    monkeypatch.delenv("AEROSWARM_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-ours")
    with pytest.raises(RuntimeError, match="AEROSWARM_ANTHROPIC_API_KEY"):
        AnthropicClient(TraceLogger(None))


def test_scripted_client_checks_schema():
    c = ScriptedClient([MEMO])
    with pytest.raises(TypeError):
        c.structured("critic", "s", "u", Verdict)
