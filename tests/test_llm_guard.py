"""Guard against a silently degraded "real LLM" run.

1. --llm anthropic without an API key (either variable) fails at startup, before a run directory exists.
2. Calls and fallbacks are counted per agent; more than 2 failed calls aborts the run, and a run
   in which any agent never got a successful call is invalid. Invalid runs fail require_real_llm().
"""

import json
from collections import Counter
from types import SimpleNamespace

import pytest

from swarm.llm.client import (
    AGENTS,
    API_KEY_ENV,
    API_KEY_FALLBACK_ENV,
    MAX_FAILED_CALLS,
    PRICES,
    AnthropicClient,
    InvalidLLMRun,
    LLMHealth,
    MissingAPIKey,
    TraceLogger,
    estimate_cost,
    make_client,
    require_real_llm,
)
from swarm.llm.mock import MockClient
from swarm.run import main, run
from swarm.state import StrategyMemo

MEMO = StrategyMemo(
    hypothesis="h", focus_params=["alpha_deg"], trust_radius=0.1, fidelity="neuralfoil", mode="reasoned_step"
)
USAGE = SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0, cache_creation_input_tokens=0)


KEY_VARS = (API_KEY_ENV, API_KEY_FALLBACK_ENV)


@pytest.fixture
def no_key(monkeypatch):
    for var in (*KEY_VARS, "AEROSWARM_LLM"):
        monkeypatch.delenv(var, raising=False)


# ------------------------------------------------------------------ 1. startup key check


def test_cli_anthropic_without_key_fails_at_startup(tmp_path, no_key, capsys):
    with pytest.raises(SystemExit) as e:
        main(
            [
                "--llm",
                "anthropic",
                "--preset",
                "hard",
                "--max-evals",
                "15",
                "--budget-usd",
                "2",
                "--runs-root",
                str(tmp_path),
            ]
        )
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert API_KEY_ENV in err and API_KEY_FALLBACK_ENV in err
    assert list(tmp_path.iterdir()) == []  # no run directory, no half-written run


@pytest.mark.parametrize("var", KEY_VARS)
@pytest.mark.parametrize("key", ["", "   "])
def test_blank_key_counts_as_missing(tmp_path, no_key, monkeypatch, var, key):
    monkeypatch.setenv(var, key)
    with pytest.raises(SystemExit):
        main(["--llm", "anthropic", "--runs-root", str(tmp_path)])
    assert list(tmp_path.iterdir()) == []


def test_env_selected_anthropic_also_needs_the_key(tmp_path, no_key, monkeypatch):
    monkeypatch.setenv("AEROSWARM_LLM", "anthropic")
    with pytest.raises(SystemExit):
        main(["--runs-root", str(tmp_path)])  # --llm auto, but the env var forces Anthropic
    assert list(tmp_path.iterdir()) == []


def test_library_entry_points_refuse_too(tmp_path, no_key, spec, start):
    with pytest.raises(MissingAPIKey):
        run(spec, start, run_id="x", runs_root=tmp_path, which="anthropic")
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(MissingAPIKey):
        make_client(TraceLogger(None), "anthropic")
    with pytest.raises(MissingAPIKey):
        AnthropicClient(TraceLogger(None))  # direct construction, no injected SDK


def test_auto_and_mock_do_not_need_a_key(no_key):
    assert make_client(TraceLogger(None), "auto").is_mock  # unchanged: labelled mock
    assert make_client(TraceLogger(None), "mock").is_mock


@pytest.mark.parametrize("var", KEY_VARS)
def test_with_a_key_under_either_name_the_client_is_built(no_key, monkeypatch, var):
    monkeypatch.setenv(var, "sk-test-not-real")
    monkeypatch.delenv("AEROSWARM_MODEL", raising=False)
    c = make_client(TraceLogger(None), "anthropic")
    assert isinstance(c, AnthropicClient) and not c.is_mock and c.label == "anthropic:claude-opus-5-5"
    assert c._sdk.api_key == "sk-test-not-real"
    assert not make_client(TraceLogger(None), "auto").is_mock  # auto picks Anthropic once a key exists


def test_sonnet_5_is_priced_so_the_cost_cap_does_not_trip_on_it():
    assert PRICES["claude-sonnet-5"] == (2.0, 10.0, 0.20, 2.50)
    assert estimate_cost("claude-sonnet-5", {"input_tokens": 1_000_000}) == pytest.approx(2.0)
    assert estimate_cost("claude-sonnet-5", {"output_tokens": 1_000_000}) == pytest.approx(10.0)
    t = TraceLogger(None)
    t.log(
        role="chief", client="anthropic", model="claude-sonnet-5", schema="S", system="", user="", output=None,
        usage={"input_tokens": 5000, "output_tokens": 1000}, latency_s=0.0,
    )  # fmt: skip
    assert t.totals["cost_unknown_calls"] == 0 and not t.over_budget(2.0)


# ------------------------------------------------------------------ 2a. counting


class ScriptSDK:
    """parse() replays outcomes: an Exception is raised, 'refusal'/'empty' give an unusable response."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kw):
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        parsed = None if o in ("refusal", "empty") else MEMO
        stop = "refusal" if o == "refusal" else "end_turn"
        return SimpleNamespace(parsed_output=parsed, usage=USAGE, model="claude-opus-5-5", stop_reason=stop)


def _call(c, role):
    try:
        c.structured(role, "s", "u", StrategyMemo)
    except Exception:
        pass


def test_every_outcome_is_counted_per_agent_and_survives_a_resume(tmp_path):
    path = tmp_path / "traces.jsonl"
    sdk = ScriptSDK(["ok", ConnectionError("down"), "refusal", "empty", "ok", "ok"])
    c = AnthropicClient(TraceLogger(path), sdk_client=sdk)
    for role in ("chief", "cad", "critic", "critic", "chief", "cad"):
        _call(c, role)
    c.trace.log_fallback("critic", "numeric_verdict", RuntimeError("x"))
    c.trace.log_fallback("critic", "numeric_verdict")
    a = c.trace.health.agents
    assert a == {
        "chief": {"ok": 2, "failed": 0, "fallbacks": 0},
        "cad": {"ok": 1, "failed": 1, "fallbacks": 0},  # a raised SDK error
        "critic": {"ok": 0, "failed": 2, "fallbacks": 2},  # a refusal and an empty parse
    }
    assert c.trace.health.failed_total == 3
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert [x["type"] for x in lines].count("llm_failure") == 1 and [x["type"] for x in lines].count(
        "llm_fallback"
    ) == 2
    assert [x["ok"] for x in lines if x["type"] == "llm_call"] == [True, False, False, True, True]
    assert "ConnectionError" in next(x for x in lines if x["type"] == "llm_failure")["error"]
    # a resumed run counts what happened before it
    assert TraceLogger(path).health.agents == a


def test_health_rules():
    h = LLMHealth()
    assert h.max_failed == MAX_FAILED_CALLS == 2
    for _ in range(2):
        h.record_call("chief", False)
    assert not h.exceeded() and not h.invalid  # 2 failures are tolerated
    h.record_call("chief", False)
    assert h.exceeded() and h.invalid  # the 3rd is not
    assert "3 LLM calls failed" in h.check()[0]

    h = LLMHealth()
    h.record_call("chief", True)
    h.record_call("critic", False)
    reasons = h.check(final=True)
    assert reasons == ["cad: no successful call (never called)", "critic: no successful call (all 1 call(s) failed)"]
    assert h.invalid and h.snapshot(True)["valid"] is False
    assert h.snapshot(False)["valid"] is True  # the mock is not enforced
    for role in AGENTS:
        h.record_call(role, True)
    assert h.check(final=True) == [] and not h.invalid and h.snapshot(True)["valid"]


# ------------------------------------------------------------------ 2b. require_real_llm


def _meta(**health):
    base = {
        "enforced": True,
        "valid": True,
        "invalid_reasons": [],
        "max_failed_calls": 2,
        "failed_calls": 0,
        "agents": {},
    }
    return {
        "run_id": "r",
        "llm_client": "anthropic:m",
        "is_mock": False,
        "termination": "eval_budget",
        "llm_health": {**base, **health},
    }


def test_require_real_llm_rejects_invalid_runs_in_every_form(tmp_path):
    require_real_llm(_meta())  # a valid real run passes
    bad = _meta(valid=False, invalid_reasons=["critic: no successful call (never called)"])
    with pytest.raises(InvalidLLMRun, match="critic: no successful call"):
        require_real_llm(bad)
    with pytest.raises(ValueError):  # InvalidLLMRun is a ValueError, like the mock rejection
        require_real_llm(bad)
    (tmp_path / "meta.json").write_text(json.dumps(bad))
    for form in (tmp_path, tmp_path / "meta.json", str(tmp_path)):
        with pytest.raises(InvalidLLMRun):
            require_real_llm(form)
    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()
    (ok_dir / "meta.json").write_text(json.dumps(_meta()))
    require_real_llm(ok_dir)
    with pytest.raises(InvalidLLMRun, match="no llm_health"):  # unfinished / pre-validity runs
        require_real_llm({"run_id": "old", "is_mock": False})
    with pytest.raises(InvalidLLMRun):  # termination alone is enough
        require_real_llm({**_meta(), "termination": "invalid_llm"})
    with pytest.raises(ValueError, match="not an LLM"):
        require_real_llm({**_meta(), "is_mock": True})


def test_require_real_llm_rejects_a_client_whose_run_went_invalid():
    c = AnthropicClient(TraceLogger(None), sdk_client=ScriptSDK(["ok"] + [ConnectionError("x")] * 3))
    require_real_llm(c)  # fresh client: nothing has failed yet
    for _ in range(4):
        _call(c, "chief")
    with pytest.raises(InvalidLLMRun, match="3 LLM calls failed"):
        require_real_llm(c)


# ------------------------------------------------------------------ 2c. graph runs


class BackedClient(AnthropicClient):
    """The real AnthropicClient bookkeeping (counts, traces, validity) over MockClient answers.

    fail(role, n) -> True makes that role's n-th call raise inside the SDK, as an outage would.
    """

    def __init__(self, trace, fail=lambda role, n: False):
        self.calls, self.order, self._fail = Counter(), [], fail
        self._mock = MockClient(TraceLogger(None), inject_faults=False)
        sdk = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=self._parse)))
        super().__init__(trace, model="claude-opus-5-5", sdk_client=sdk)

    def structured(self, role, system, user, schema, facts=None):
        self._role, self._facts = role, facts
        return super().structured(role, system, user, schema, facts=facts)

    def _parse(self, **kw):
        role = self._role
        self.calls[role] += 1
        self.order.append(role)
        if self._fail(role, self.calls[role]):
            raise ConnectionError(f"simulated outage: {role} call {self.calls[role]}")
        out = self._mock.structured(role, "", "", kw["output_format"], facts=self._facts)
        return SimpleNamespace(parsed_output=out, usage=USAGE, stop_reason="end_turn", model="claude-opus-5-5")


def _go(tmp_path, spec, start, rid, fail=lambda role, n: False, max_evals=None):
    s = spec if max_evals is None else spec.model_copy(update={"max_evals": max_evals})
    llm = BackedClient(TraceLogger(tmp_path / rid / "traces.jsonl"), fail)
    final = run(s, start, run_id=rid, runs_root=tmp_path, llm=llm)
    meta = json.loads((tmp_path / rid / "meta.json").read_text())
    return llm, final, meta, (tmp_path / rid / "report.md").read_text()


def test_healthy_real_run_reports_counts_and_is_valid(tmp_path, spec, start, fake_xfoil):
    fake_xfoil()
    llm, final, meta, report = _go(tmp_path, spec, start, "ok")
    h = meta["llm_health"]
    assert h["enforced"] and h["valid"] and h["invalid_reasons"] == [] and h["failed_calls"] == 0
    assert all(h["agents"][a]["ok"] == llm.calls[a] > 0 for a in AGENTS)
    assert meta["termination"] == final["termination"] == "target_met"
    assert "## LLM calls by agent" in report and "LLM health: **valid**" in report
    assert f"| chief | {llm.calls['chief']} | 0 | 0 |" in report and "INVALID" not in report
    require_real_llm(tmp_path / "ok")


def test_two_failed_calls_are_tolerated_and_their_fallbacks_counted(tmp_path, spec, start, fake_xfoil):
    fake_xfoil()
    fail = lambda role, n: (role, n) in {("chief", 2), ("critic", 1)}  # noqa: E731
    llm, final, meta, report = _go(tmp_path, spec, start, "two", fail)
    h = meta["llm_health"]
    assert h["valid"] and h["failed_calls"] == 2 and meta["termination"] != "invalid_llm"
    assert h["agents"]["chief"]["failed"] == 1 and h["agents"]["chief"]["fallbacks"] == 1
    assert h["agents"]["critic"]["failed"] == 1 and h["agents"]["critic"]["fallbacks"] == 1
    assert h["agents"]["cad"] == {"ok": llm.calls["cad"], "failed": 0, "fallbacks": 0}
    assert f"| chief | {llm.calls['chief'] - 1} | 1 | 1 |" in report and "| **total** |" in report
    events = [
        json.loads(x)["event"] for x in (tmp_path / "two" / "events.jsonl").read_text().splitlines() if "event" in x
    ]
    assert "llm_error_reused_strategy" in events and "llm_error_numeric_verdict" in events
    require_real_llm(tmp_path / "two")


def test_third_failed_call_aborts_the_run_and_marks_it_invalid(tmp_path, spec, start, fake_xfoil):
    fake_xfoil()
    llm, final, meta, report = _go(tmp_path, spec, start, "abort", fail=lambda role, n: role == "critic")
    h = meta["llm_health"]
    assert final["termination"] == meta["termination"] == "invalid_llm"
    assert h["valid"] is False and h["failed_calls"] == 3 and "3 LLM calls failed" in h["invalid_reasons"][0]
    assert llm.calls["critic"] == 3 and llm.order[-1] == "critic"  # no LLM call after the 3rd failure
    events = [json.loads(x) for x in (tmp_path / "abort" / "events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "terminated" and events[-1]["reason"] == "invalid_llm"
    assert "INVALID RUN" in report and "LLM health: **INVALID**" in report and "Termination: **invalid_llm**" in report
    with pytest.raises(InvalidLLMRun):
        require_real_llm(tmp_path / "abort")
    with pytest.raises(InvalidLLMRun):
        require_real_llm(llm)  # and the client itself


def test_an_agent_that_never_succeeds_invalidates_even_under_the_failure_limit(tmp_path, spec, start, fake_xfoil):
    fake_xfoil()
    llm, final, meta, report = _go(
        tmp_path, spec, start, "nocritic", fail=lambda role, n: role == "critic", max_evals=2
    )
    h = meta["llm_health"]
    assert h["failed_calls"] == 2 and not (h["failed_calls"] > MAX_FAILED_CALLS)  # not the abort rule
    assert meta["termination"] == "invalid_llm" and h["valid"] is False
    assert h["invalid_reasons"] == ["critic: no successful call (all 2 call(s) failed)"]
    with pytest.raises(InvalidLLMRun, match="critic"):
        require_real_llm(tmp_path / "nocritic")


def test_an_agent_that_was_never_called_invalidates(tmp_path, spec, start, fake_xfoil):
    fake_xfoil()
    llm, final, meta, report = _go(tmp_path, spec, start, "nocad", max_evals=1)  # the baseline needs no CAD call
    assert llm.calls["cad"] == 0
    assert meta["termination"] == "invalid_llm"
    assert meta["llm_health"]["invalid_reasons"] == ["cad: no successful call (never called)"]


def test_cli_exits_nonzero_on_an_invalid_run(tmp_path, spec, fake_xfoil, monkeypatch, capsys):
    fake_xfoil()
    monkeypatch.setenv(API_KEY_ENV, "sk-test-not-real")
    monkeypatch.setattr(
        "swarm.run.make_client",
        lambda trace, which, inject_faults=False: BackedClient(trace, lambda role, n: role == "critic"),
    )
    with pytest.raises(SystemExit) as e:
        main(
            [
                "--llm",
                "anthropic",
                "--preset",
                "hard",
                "--max-evals",
                "15",
                "--budget-usd",
                "2",
                "--runs-root",
                str(tmp_path),
                "--run-id",
                "cli",
            ]
        )
    assert e.value.code == 3
    cap = capsys.readouterr()
    assert '"llm_valid": false' in cap.out and "INVALID RUN" in cap.err
    with pytest.raises(InvalidLLMRun):
        require_real_llm(tmp_path / "cli")


def test_mock_runs_are_not_enforced(tmp_path, spec, start, fake_xfoil):
    fake_xfoil()
    final = run(spec, start, run_id="m", runs_root=tmp_path, which="mock")
    h = json.loads((tmp_path / "m" / "meta.json").read_text())["llm_health"]
    assert final["termination"] == "target_met" and h["enforced"] is False and h["valid"] is True
    assert "not enforced (mock)" in (tmp_path / "m" / "report.md").read_text()
    with pytest.raises(ValueError, match="not an LLM"):  # still never an LLM arm
        require_real_llm(tmp_path / "m")
