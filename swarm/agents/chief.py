"""Chief Aerodynamicist: owns the search strategy. Output: StrategyMemo."""

from __future__ import annotations

from swarm.briefs import chief_brief
from swarm.llm.client import LLMClient
from swarm.state import FIDELITY_RANK, StrategyMemo, SwarmState, free_params

AVAILABLE_FIDELITIES = ("neuralfoil", "xfoil")  # of2d/of3d arrive with the OpenFOAM milestone


def plan(llm: LLMClient, state: SwarmState, sens: dict) -> tuple[StrategyMemo, list[dict]]:
    """Returns the (sanitized) memo plus events describing any coercion."""
    b = chief_brief(state, sens)
    memo = llm.structured("chief", b.system, b.user, StrategyMemo, facts=b.facts)
    return sanitize(memo, state)


def sanitize(memo: StrategyMemo, state: SwarmState) -> tuple[StrategyMemo, list[dict]]:
    spec, events, upd = state["spec"], [], {}
    gen = state.get("generation", 0)
    free = free_params(spec)
    focus = [p for p in memo.focus_params if p in free][:3]
    if focus != memo.focus_params:
        events.append(
            {
                "node": "chief_plan",
                "gen": gen,
                "event": "focus_params_coerced",
                "requested": memo.focus_params,
                "used": focus or list(free[:3]),
            }
        )
        upd["focus_params"] = focus or list(free[:3])
    if memo.mode == "inner_optimizer":
        events.append(
            {
                "node": "chief_plan",
                "gen": gen,
                "event": "inner_optimizer_unavailable",
                "detail": "treated as reasoned_step until milestone 4",
            }
        )
        upd["mode"], upd["inner_budget"] = "reasoned_step", 0
    if memo.fidelity not in AVAILABLE_FIDELITIES:
        events.append(
            {
                "node": "chief_plan",
                "gen": gen,
                "event": "fidelity_unavailable",
                "requested": memo.fidelity,
                "used": "xfoil",
            }
        )
        upd["fidelity"] = "xfoil"
    if memo.promote_cid:
        known = {r.params.cid: r for r in state.get("ledger", [])}
        rec = known.get(memo.promote_cid)
        fid = upd.get("fidelity", memo.fidelity)
        if rec is None or FIDELITY_RANK[fid] <= FIDELITY_RANK[rec.result.fidelity]:
            events.append(
                {
                    "node": "chief_plan",
                    "gen": gen,
                    "event": "promotion_rejected",
                    "cid": memo.promote_cid,
                    "reason": "unknown cid or not a higher tier",
                }
            )
            upd["promote_cid"] = None
    return (memo.model_copy(update=upd) if upd else memo), events
