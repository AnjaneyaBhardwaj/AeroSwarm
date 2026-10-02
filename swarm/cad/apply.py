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
    kind: Literal["unknown_param", "not_allowed", "direction", "bounds", "trust_region", "duplicate", "no_change"]
    msg: str
    hint: str = ""

    def render(self) -> str:
        return f"{self.kind}: {self.msg}" + (f" (hint: {self.hint})" if self.hint else "")


class ProposalResult(BaseModel):
    ok: bool
    params: WingParams | None = None
    error: ToolError | None = None
    # changes that go against the Chief's direction, each with the CAD's override reason
    disagreements: list[dict] = []


# A proposal within these of an evaluated design (every parameter) is a near-duplicate: it costs an
# evaluation and tells us nothing new (live run 2, gens 9-11: alpha nudged by 0.002 deg).
NEAR_DUP_TOL: dict[str, float] = {
    "alpha_deg": 0.05,
    "main_camber": 0.002,
    "main_camber_pos": 0.002,
    "main_thickness": 0.002,
}
EXACT_TOL = 1e-4  # quantization step: every other parameter must match


def near_duplicate(params: WingParams, ledger: list[EvalRecord], fidelity: str) -> EvalRecord | None:
    """The latest record at `fidelity` whose design is within NEAR_DUP_TOL of `params` (exact match included)."""
    p = params.model_dump()
    for rec in reversed(ledger):
        if rec.result.fidelity != fidelity:
            continue
        q = rec.params.model_dump()
        if all(abs(p[k] - q[k]) <= NEAR_DUP_TOL.get(k, EXACT_TOL) + 1e-12 for k in p):
            return rec
    return None


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
    allowed = set(strategy.focus_names) & set(free_params(spec))
    bounds = WingParams.bounds()
    updates: dict[str, float] = {}
    disagreements: list[dict] = []
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
        want = strategy.direction(ch.name)
        moved = "+" if ch.new_value > getattr(base, ch.name) else "-"
        if want != "free" and abs(ch.new_value - getattr(base, ch.name)) >= 1e-4 and moved != want:
            if not ch.override_reason.strip():
                return ProposalResult(
                    ok=False,
                    error=ToolError(
                        kind="direction",
                        msg=f"{ch.name} moves {moved} but the Chief asked for {want}",
                        hint="follow the Chief's direction, or give override_reason for this change",
                    ),
                )
            disagreements.append({"param": ch.name, "chief": want, "cad": moved, "reason": ch.override_reason.strip()})
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
    rec = near_duplicate(params, ledger, strategy.fidelity)
    if rec is not None:
        r = rec.result
        nums = f"Cl={r.cl:.3f}, Cd={r.cd:.4f}" if r.cl is not None and r.cd is not None else r.status
        if rec.params.cid == params.cid:
            msg = f"already evaluated: {nums}"
        else:
            msg = f"within tolerance of {rec.params.cid} (gen {rec.generation}), already evaluated: {nums}"
        tol = ", ".join(f"{k} {v:g}" for k, v in NEAR_DUP_TOL.items())
        return ProposalResult(
            ok=False,
            error=ToolError(
                kind="duplicate", msg=msg, hint=f"propose something different (near-duplicate tolerance: {tol})"
            ),
        )
    return ProposalResult(ok=True, params=params, disagreements=disagreements)


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
    names = [n for n in strategy.focus_names if n in free_params(spec)] or list(free_params(spec))
    for _ in range(50):
        upd = {}
        for n in names:
            a, b = allowed_interval(n, best, strategy.trust_radius * radius_frac)
            upd[n] = quantize(rng.uniform(a, b))
        p = WingParams(**{**best.model_dump(), **upd})
        if p.cid != best.cid and near_duplicate(p, ledger, strategy.fidelity) is None:
            return p
    return best
