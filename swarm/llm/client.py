"""The single LLM wrapper. Every agent call goes through `LLMClient.structured`.

Clients:
  AnthropicClient — the real model, structured output via `messages.parse`.
  MockClient      — deterministic rule-based stand-in. FOR TESTS AND DEMOS
                    ONLY. It is NOT an LLM and must never be used as the
                    "LLM" arm of a comparison or ablation (see
                    `require_real_llm`).
  ScriptedClient  — replays pre-built objects, for tests that force a branch.

Every call is appended to runs/<id>/traces.jsonl with prompt, output, tokens,
latency and estimated cost; `TraceLogger.summary()` gives the run totals.

Run validity: `LLMHealth` (on the TraceLogger) counts successful and failed calls and
fallbacks per agent. A real-LLM run with more than `MAX_FAILED_CALLS` failed calls, or in
which any agent never got a successful call, is INVALID; `require_real_llm` refuses it.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

API_KEY_ENV = "AEROSWARM_ANTHROPIC_API_KEY"
API_KEY_FALLBACK_ENV = "ANTHROPIC_API_KEY"  # the SDK's own name; used only when API_KEY_ENV is unset or empty
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"


def resolve_api_key() -> str | None:
    """AEROSWARM_ANTHROPIC_API_KEY first, then ANTHROPIC_API_KEY; empty or blank counts as unset."""
    for var in (API_KEY_ENV, API_KEY_FALLBACK_ENV):
        if value := os.environ.get(var, "").strip():
            return value
    return None


# USD per million tokens: (input, output, cache_read, cache_write_5m).
# Source: https://platform.claude.com/docs/en/about-claude/pricing, fetched 2026-10-01 (every
# row below matches that page; it names models by display name, e.g. "Claude Sonnet 5", and
# the ids here follow our AEROSWARM_MODEL / API naming). 1h cache writes are not modelled.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    # Sonnet 5: $2 in / $10 out, 5m cache write $2.50, cache hit $0.20 (page footnote 3: the
    # launch-time "introductory" $2/$10 is now the standard price; the $3/$15 step-up was cancelled).
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25),
}


def estimate_cost(model: str, usage: dict[str, int]) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    return (
        usage.get("input_tokens", 0) * p[0]
        + usage.get("output_tokens", 0) * p[1]
        + usage.get("cache_read_input_tokens", 0) * p[2]
        + usage.get("cache_creation_input_tokens", 0) * p[3]
    ) / 1e6


class LLMRefusal(RuntimeError):
    pass


class MissingAPIKey(RuntimeError):
    """A real-LLM run was requested but no API key is set (see `resolve_api_key`)."""


class InvalidLLMRun(ValueError):
    """A real-LLM run that failed its validity rules; it cannot be an LLM arm of anything."""


# The agents that must each get at least one successful call in a valid real-LLM run.
AGENTS = ("chief", "cad", "critic")
MAX_FAILED_CALLS = 2  # more than this many failed calls aborts the run


class LLMHealth:
    """Per-agent LLM call outcomes, and whether a real-LLM run can still be trusted.

    ok        calls that returned a usable structured output
    failed    calls that raised, were refused, or returned nothing
    fallbacks times the graph replaced an agent's output with a deterministic one
              (Chief: reused strategy; CAD: deterministic proposal; Critic: numeric-only verdict)

    INVALID when more than `max_failed` calls failed (the graph aborts at the first call past
    the limit) or, checked at the end of the run, any agent never got a successful call
    (including never being called at all). Exception: the CAD agent in a hybrid run whose CAD
    steps were all replaced by inner-optimizer runs and promotions (the graph passes `not_needed`).
    """

    def __init__(self, max_failed: int = MAX_FAILED_CALLS):
        self.max_failed = max_failed
        self.agents: dict[str, dict[str, int]] = {a: self._blank() for a in AGENTS}
        self.invalid_reasons: list[str] = []
        self._lock = threading.Lock()

    @staticmethod
    def _blank() -> dict[str, int]:
        return {"ok": 0, "failed": 0, "fallbacks": 0}

    def record_call(self, role: str, ok: bool) -> None:
        with self._lock:
            self.agents.setdefault(role, self._blank())["ok" if ok else "failed"] += 1

    def record_fallback(self, role: str) -> None:
        with self._lock:
            self.agents.setdefault(role, self._blank())["fallbacks"] += 1

    @property
    def failed_total(self) -> int:
        return sum(r["failed"] for r in self.agents.values())

    def exceeded(self) -> bool:
        return self.failed_total > self.max_failed

    def check(self, final: bool = False, not_needed: frozenset[str] | set[str] = frozenset()) -> list[str]:
        """Recompute the invalid reasons from the counts. `final=True` at the end of a run.

        `not_needed`: agents the run never asked for (e.g. the CAD agent when every generation was a
        promotion or an inner-optimizer run). Such an agent with no call at all is not a failure; one
        that was called and never succeeded still is."""
        reasons = []
        if self.exceeded():
            reasons.append(f"{self.failed_total} LLM calls failed (more than {self.max_failed} aborts the run)")
        if final:
            for a in AGENTS:
                r = self.agents[a]
                if r["ok"] == 0 and not (a in not_needed and r["failed"] == 0 and r["fallbacks"] == 0):
                    why = "never called" if r["failed"] == 0 else f"all {r['failed']} call(s) failed"
                    reasons.append(f"{a}: no successful call ({why})")
        self.invalid_reasons = reasons
        return list(reasons)

    @property
    def invalid(self) -> bool:
        return self.exceeded() or bool(self.invalid_reasons)

    def snapshot(self, enforced: bool) -> dict:
        reasons = list(self.invalid_reasons) if enforced else []
        return {
            "enforced": enforced,  # False for the mock, which is never a valid LLM arm anyway
            "valid": not reasons,
            "invalid_reasons": reasons,
            "max_failed_calls": self.max_failed,
            "failed_calls": self.failed_total,
            "agents": {k: dict(v) for k, v in self.agents.items()},
        }


class TraceLogger:
    """Appends one JSON line per LLM call; keeps running token/cost totals.

    Opening an existing traces.jsonl (a resumed run) reloads the totals from its
    `llm_call` lines, so a cost cap counts spend from before the resume.
    """

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.totals = {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cost_usd": 0.0,
            "cost_unknown_calls": 0,
        }
        self.health = LLMHealth()
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                self._reload()

    def _add(self, usage: dict[str, int], cost: float | None) -> None:
        self.totals["calls"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            self.totals[k] += int(usage.get(k, 0) or 0)
        if cost is None:
            self.totals["cost_unknown_calls"] += 1
        else:
            self.totals["cost_usd"] += cost

    def _reload(self) -> None:
        for line in self.path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line from a crash
            kind = rec.get("type")
            if kind == "llm_call":
                self._add(rec.get("usage") or {}, rec.get("cost_usd"))
                self.health.record_call(rec.get("role", "?"), bool(rec.get("ok", True)))
            elif kind == "llm_failure":
                self.health.record_call(rec.get("role", "?"), False)
            elif kind == "llm_fallback":
                self.health.record_fallback(rec.get("role", "?"))

    def _write(self, rec: dict) -> None:
        if self.path:
            with self._lock, self.path.open("a") as f:
                f.write(json.dumps(rec, default=str) + "\n")

    def log(
        self,
        *,
        role: str,
        client: str,
        model: str,
        schema: str,
        system: str,
        user: str,
        output: Any,
        usage: dict[str, int],
        latency_s: float,
        extra: dict | None = None,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        """One call that got a response. `ok=False`: the response was unusable (refusal, no output)."""
        cost = estimate_cost(model, usage) if usage else 0.0
        with self._lock:
            self._add(usage, cost)
        self.health.record_call(role, ok)
        self._write(
            {
                "type": "llm_call",
                "ts": time.time(),
                "role": role,
                "client": client,
                "model": model,
                "schema": schema,
                "system": system,
                "user": user,
                "output": output,
                "usage": usage,
                "latency_s": round(latency_s, 4),
                "cost_usd": cost,
                "ok": ok,
                **({"error": error} if error else {}),
                **(extra or {}),
            }
        )

    def log_failure(
        self, *, role: str, client: str, model: str, schema: str, error: BaseException, latency_s: float
    ) -> None:
        """A call that raised before any usable response (auth, network, API error, bad parse)."""
        self.health.record_call(role, False)
        self._write(
            {
                "type": "llm_failure",
                "ts": time.time(),
                "role": role,
                "client": client,
                "model": model,
                "schema": schema,
                "error": f"{type(error).__name__}: {error}"[:500],
                "latency_s": round(latency_s, 4),
            }
        )

    def log_fallback(self, role: str, kind: str, error: BaseException | None = None) -> None:
        """The graph replaced `role`'s output with a deterministic one (`kind`)."""
        self.health.record_fallback(role)
        self._write(
            {
                "type": "llm_fallback",
                "ts": time.time(),
                "role": role,
                "kind": kind,
                **({"error": f"{type(error).__name__}: {error}"[:500]} if error else {}),
            }
        )

    def over_budget(self, cap_usd: float | None) -> bool:
        """True once estimated spend reaches `cap_usd`.

        A call whose cost cannot be estimated (model missing from PRICES) counts
        as over budget: with a cap set, unknown spend is never assumed to be zero.
        """
        if cap_usd is None:
            return False
        return self.totals["cost_unknown_calls"] > 0 or self.totals["cost_usd"] >= cap_usd

    def summary(self) -> dict:
        return {"type": "run_summary", "ts": time.time(), **self.totals, "cost_usd": round(self.totals["cost_usd"], 6)}

    def write_summary(self, extra: dict | None = None) -> dict:
        s = {**self.summary(), **(extra or {})}
        self._write(s)
        return s


class LLMClient(Protocol):
    kind: str  # "anthropic" | "mock" | "scripted"
    is_mock: bool
    label: str  # what goes in run metadata

    def structured(self, role: str, system: str, user: str, schema: type[T], facts: dict | None = None) -> T: ...


def _meta_of(source: Any) -> dict:
    if isinstance(source, dict):
        return source
    path = Path(source)
    path = path / "meta.json" if path.is_dir() else path
    return json.loads(path.read_text())


def require_real_llm(source: Any) -> None:
    """Gate for any comparison/ablation runner: only a real, valid LLM run may be the LLM arm.

    `source` is a client, or a finished run (run dir, its meta.json path, or the meta dict).
    Rejects mocks, and rejects any run that is INVALID (too many failed LLM calls, or an agent
    that never got a successful call), unfinished, or recorded before validity tracking.
    """
    if isinstance(source, dict | str | os.PathLike):
        meta = _meta_of(source)
        label = meta.get("llm_client") or meta.get("run_id") or "run"
        if meta.get("is_mock"):
            raise ValueError(f"{label} is not an LLM; it cannot be the LLM arm of a comparison")
        health = meta.get("llm_health")
        if health is None:
            raise InvalidLLMRun(f"{label}: no llm_health record (unfinished run, or written before validity tracking)")
        if health.get("valid") is not True or meta.get("termination") == "invalid_llm":
            reasons = "; ".join(health.get("invalid_reasons") or ["marked invalid"])
            raise InvalidLLMRun(f"{label}: invalid LLM run: {reasons}")
        return
    if source.is_mock:
        raise ValueError(f"{source.label} is not an LLM; it cannot be the LLM arm of a comparison")
    health = getattr(getattr(source, "trace", None), "health", None)
    if health is not None and health.invalid:
        reasons = "; ".join(health.invalid_reasons or health.check()) or "marked invalid"
        raise InvalidLLMRun(f"{source.label}: invalid LLM run: {reasons}")


def require_api_key() -> str:
    """The API key, or MissingAPIKey (a RuntimeError) naming both variables."""
    key = resolve_api_key()
    if key is None:
        raise MissingAPIKey(
            f"{API_KEY_ENV} (or {API_KEY_FALLBACK_ENV}) is not set, so a real-LLM run is impossible (the Anthropic "
            "SDK would only fail at the first call). Export one, or use --llm mock for the labelled stand-in."
        )
    return key


def resolve_llm_choice(which: str = "auto") -> str:
    """'anthropic' or 'mock'. AEROSWARM_LLM overrides `which`; 'auto' means Anthropic iff a key is set."""
    which = os.environ.get("AEROSWARM_LLM", which)
    return "anthropic" if which == "anthropic" or (which == "auto" and resolve_api_key()) else "mock"


def preflight_llm(which: str = "auto") -> None:
    """Fail at startup, before any run directory exists, if the chosen LLM cannot run."""
    if resolve_llm_choice(which) == "anthropic":
        require_api_key()


class AnthropicClient:
    kind = "anthropic"
    is_mock = False

    def __init__(
        self,
        trace: TraceLogger,
        model: str | None = None,
        effort: str | None = None,
        sdk_client: Any = None,
        max_tokens: int = 16000,
    ):
        self.trace = trace
        self.model = model or os.environ.get("AEROSWARM_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("AEROSWARM_EFFORT", DEFAULT_EFFORT)
        self.max_tokens = max_tokens
        if sdk_client is None:
            api_key = require_api_key()
            import anthropic

            sdk_client = anthropic.Anthropic(api_key=api_key)
        self._sdk = sdk_client
        self.label = f"anthropic:{self.model}"

    def structured(self, role, system, user, schema, facts=None):
        t0 = time.perf_counter()
        try:
            resp = self._sdk.beta.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                # Server-side refusal fallback: routes a declined request to another model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except Exception as e:
            self.trace.log_failure(
                role=role,
                client=self.kind,
                model=self.model,
                schema=schema.__name__,
                error=e,
                latency_s=time.perf_counter() - t0,
            )
            raise
        latency = time.perf_counter() - t0
        u = resp.usage
        usage = {
            k: int(getattr(u, k, 0) or 0)
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        }
        served = getattr(resp, "model", self.model) or self.model
        parsed = getattr(resp, "parsed_output", None)
        error: Exception | None = None
        if resp.stop_reason == "refusal":
            error = LLMRefusal(f"{role}: model declined ({getattr(resp, 'stop_details', None)})")
        elif parsed is None:
            error = ValueError(f"{role}: no structured output (stop_reason={resp.stop_reason})")
        self.trace.log(
            role=role,
            client=self.kind,
            model=served,
            schema=schema.__name__,
            system=system,
            user=user,
            output=parsed.model_dump() if parsed is not None else None,
            usage=usage,
            latency_s=latency,
            extra={"stop_reason": resp.stop_reason, "requested_model": self.model},
            ok=error is None,
            error=None if error is None else str(error)[:500],
        )
        if error is not None:
            raise error
        return parsed


class ScriptedClient:
    """Replays queued responses in order. Tests only."""

    kind = "scripted"
    is_mock = True
    label = "scripted (test replay, not an LLM)"

    def __init__(self, responses: list[BaseModel], trace: TraceLogger | None = None):
        self.responses = list(responses)
        self.trace = trace or TraceLogger(None)
        self.calls: list[dict] = []

    def structured(self, role, system, user, schema, facts=None):
        self.calls.append({"role": role, "schema": schema.__name__, "system": system, "user": user})
        if not self.responses:
            raise RuntimeError(f"ScriptedClient exhausted at {role}/{schema.__name__}")
        out = self.responses.pop(0)
        if not isinstance(out, schema):
            raise TypeError(f"scripted {type(out).__name__} but {role} asked for {schema.__name__}")
        self.trace.log(
            role=role,
            client=self.kind,
            model="scripted",
            schema=schema.__name__,
            system=system,
            user=user,
            output=out.model_dump(),
            usage={},
            latency_s=0.0,
        )
        return out


def make_client(trace: TraceLogger, which: str = "auto", inject_faults: bool = False) -> LLMClient:
    """auto → Anthropic when AEROSWARM_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY) is set, else the labelled mock.

    An explicit Anthropic choice (--llm anthropic, AEROSWARM_LLM=anthropic) without a key raises
    `MissingAPIKey`; it never degrades to anything else.
    """
    if resolve_llm_choice(which) == "anthropic":
        return AnthropicClient(trace)
    from swarm.llm.mock import MockClient

    return MockClient(trace, inject_faults=inject_faults)
