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

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"

# USD per million tokens: (input, output, cache_read, cache_write_5m).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
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
            if rec.get("type") == "llm_call":
                self._add(rec.get("usage") or {}, rec.get("cost_usd"))

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
    ) -> None:
        cost = estimate_cost(model, usage) if usage else 0.0
        with self._lock:
            self._add(usage, cost)
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
                **(extra or {}),
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


def require_real_llm(client: LLMClient) -> None:
    """Call from any comparison/ablation runner before using a client as the LLM arm."""
    if client.is_mock:
        raise ValueError(f"{client.label} is not an LLM; it cannot be the LLM arm of a comparison")


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
            import anthropic

            sdk_client = anthropic.Anthropic()
        self._sdk = sdk_client
        self.label = f"anthropic:{self.model}"

    def structured(self, role, system, user, schema, facts=None):
        t0 = time.perf_counter()
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
        latency = time.perf_counter() - t0
        u = resp.usage
        usage = {
            k: int(getattr(u, k, 0) or 0)
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        }
        served = getattr(resp, "model", self.model) or self.model
        parsed = getattr(resp, "parsed_output", None)
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
        )
        if resp.stop_reason == "refusal":
            raise LLMRefusal(f"{role}: model declined ({getattr(resp, 'stop_details', None)})")
        if parsed is None:
            raise ValueError(f"{role}: no structured output (stop_reason={resp.stop_reason})")
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
    """auto → Anthropic when ANTHROPIC_API_KEY is set, else the labelled mock."""
    which = os.environ.get("AEROSWARM_LLM", which)
    if which == "anthropic" or (which == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return AnthropicClient(trace)
    from swarm.llm.mock import MockClient

    return MockClient(trace, inject_faults=inject_faults)
