"""CFD Automation Agent (numerics operator): chooses the next OpenFOAM recovery level. Output: RecoveryAction.

Mostly deterministic in normal operation; its LLM is called only after a failed of2d solve (BLUEPRINT §1).
`sanitize` enforces in code what the prompt asks: a level already tried, or out of range, is replaced by the
deterministic policy's choice (`recovery.default_level`) and the coercion is reported.
"""

from __future__ import annotations

from swarm.briefs import cfd_brief
from swarm.llm.client import LLMClient
from swarm.solvers.openfoam.recovery import default_level, next_level_allowed
from swarm.state import DesignSpec, RecoveryAction


def sanitize(action: RecoveryAction, failure: dict, tried: list[int]) -> tuple[RecoveryAction | None, str | None]:
    """(action to apply, coercion note). None when the ladder is exhausted."""
    status = failure.get("status", "diverged")
    if next_level_allowed(action.level, tried, status):
        return action, None
    lvl = default_level(failure.get("signature"), failure.get("status", "diverged"), tried)
    if lvl is None:
        return None, f"L{action.level} refused and no level left"
    if action.level in tried:
        why = "already tried"
    elif 1 <= action.level <= 5:
        why = "cannot change a mesh failure"
    else:
        why = "out of range"
    fixed = action.model_copy(
        update={"level": lvl, "rationale": f"[coerced from L{action.level}: {why}] " + action.rationale}
    )
    return fixed, f"L{action.level} {why}; L{lvl} instead"


def choose(
    llm: LLMClient, spec: DesignSpec, failure: dict, tried: list[int]
) -> tuple[RecoveryAction | None, str | None]:
    b = cfd_brief(spec, failure, tried)
    raw = llm.structured("cfd", b.system, b.user, RecoveryAction, facts=b.facts)
    return sanitize(raw, failure, tried)


def fallback(failure: dict, tried: list[int]) -> RecoveryAction | None:
    """The deterministic policy, used when the LLM call fails (counted as the agent's fallback)."""
    lvl = default_level(failure.get("signature"), failure.get("status", "diverged"), tried)
    if lvl is None:
        return None
    return RecoveryAction(level=lvl, rationale="deterministic policy (failure class preference)", evidence="")
