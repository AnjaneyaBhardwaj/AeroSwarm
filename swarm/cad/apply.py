"""`propose_delta`: the only mutating CAD tool (BLUEPRINT §2/§3 Scenario A).

Checks, in order: known/allowed parameter, schema bounds, trust region,
duplicate cid. Every rejection is a ToolError whose message goes back to
the CAD agent verbatim; the graph never sees an exception.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ValidationError

from swarm.state import (
    DesignSpec,
    EvalRecord,
    ParamDelta,
    StrategyMemo,
    WingParams,
    free_params,
    quantize,
)


class ToolError(BaseModel):
    kind: Literal["unknown_param", "not_allowed", "bounds", "trust_region", "duplicate", "no_change"]
    msg: str
    hint: str = ""

    def render(self) -> str:
        return f"{self.kind}: {self.msg}" + (f" (hint: {self.hint})" if self.hint else "")


class ProposalResult(BaseModel):
    ok: bool
    params: WingParams | None = None
    error: ToolError | None = None


def allowed_interval(name: str, base: WingParams, radius: float) -> tuple[float, float]:
    lo, hi = WingParams.bounds()[name]
    r = radius * (hi - lo)
    v = getattr(base, name)
    return max(lo, v - r), min(hi, v + r)


def apply_delta(
    base: WingParams,
    delta: ParamDelta,
    strategy: StrategyMemo,
    spec: DesignSpec,
    ledger: list[EvalRecord],
) -> ProposalResult:
    allowed = set(strategy.focus_params) & set(free_params(spec))
    bounds = WingParams.bounds()
    updates: dict[str, float] = {}
    for ch in delta.changes:
        if ch.name not in bounds:
            return ProposalResult(
                ok=False,
                error=ToolError(
                    kind="unknown_param", msg=f"{ch.name} is not a WingParams field", hint=f"allowed: {sorted(allowed)}"
                ),
            )
        if ch.name not in allowed:
            return ProposalResult(
                ok=False,
                error=ToolError(
                    kind="not_allowed",
                    msg=f"{ch.name} is not in the Chief's focus params",
                    hint=f"allowed: {sorted(allowed)}",
                ),
            )
        lo, hi = bounds[ch.name]
        if not lo <= ch.new_value <= hi:
            side = f"> max {hi}" if ch.new_value > hi else f"< min {lo}"
            return ProposalResult(
                ok=False,
                error=ToolError(kind="bounds", msg=f"{ch.name} {ch.new_value} {side}", hint=f"bounds [{lo}, {hi}]"),
            )
        a, b = allowed_interval(ch.name, base, strategy.trust_radius)
        if not a - 1e-9 <= ch.new_value <= b + 1e-9:
            return ProposalResult(
                ok=False,
                error=ToolError(
                    kind="trust_region",
                    msg=f"{ch.name} {ch.new_value} outside trust region",
                    hint=f"allowed interval [{a:.4f}, {b:.4f}]",
                ),
            )
        updates[ch.name] = ch.new_value
    try:
        params = WingParams(**{**base.model_dump(), **updates})
    except ValidationError as e:
        return ProposalResult(ok=False, error=ToolError(kind="bounds", msg=str(e.errors()[0]["msg"])))
    if params.cid == base.cid:
        return ProposalResult(
            ok=False,
            error=ToolError(
                kind="no_change",
                msg="proposal equals the current design after quantization",
                hint="change at least one parameter by more than 1e-4",
            ),
        )
    for rec in ledger:
        if rec.params.cid == params.cid and rec.result.fidelity == strategy.fidelity:
            r = rec.result
            nums = f"Cl={r.cl:.3f}, Cd={r.cd:.4f}" if r.cl is not None and r.cd is not None else r.status
            return ProposalResult(
                ok=False,
                error=ToolError(kind="duplicate", msg=f"already evaluated: {nums}", hint="propose something different"),
            )
    return ProposalResult(ok=True, params=params)


def fallback_params(
    best: WingParams,
    strategy: StrategyMemo,
    spec: DesignSpec,
    ledger: list[EvalRecord],
    seed: int,
    radius_frac: float = 0.25,
) -> WingParams:
    """Best-known design plus a small random perturbation inside the bounds and trust region."""
    rng = np.random.default_rng(seed)
    names = [n for n in strategy.focus_params if n in free_params(spec)] or list(free_params(spec))
    seen = {(r.params.cid, r.result.fidelity) for r in ledger}
    for _ in range(50):
        upd = {}
        for n in names:
            a, b = allowed_interval(n, best, strategy.trust_radius * radius_frac)
            upd[n] = quantize(rng.uniform(a, b))
        p = WingParams(**{**best.model_dump(), **upd})
        if (p.cid, strategy.fidelity) not in seen and p.cid != best.cid:
            return p
    return best
