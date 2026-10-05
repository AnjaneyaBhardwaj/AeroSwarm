"""Chief Aerodynamicist: owns the search strategy. Output: StrategyMemo."""

from __future__ import annotations

from swarm.briefs import chief_brief, pending_disagreements
from swarm.llm.client import LLMClient
from swarm.overrides import override_allowed
from swarm.state import FIDELITY_RANK, FocusParam, StrategyMemo, SwarmState, free_params

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
    focus = [f for f in memo.focus_params if f.name in free][:3]
    if [f.name for f in focus] != memo.focus_names:
        used = focus or [FocusParam(name=n) for n in free[:3]]
        events.append(
            {
                "node": "chief_plan",
                "gen": gen,
                "event": "focus_params_coerced",
                "requested": [f.model_dump() for f in memo.focus_params],
                "used": [f.model_dump() for f in used],
            }
        )
        upd["focus_params"] = used
    # Deadlock rule: a parameter the CAD overrode last generation must be adopted (CAD's direction)
    # or locked. Restating the old direction without a lock becomes a lock; "free" adopts the CAD's.
    pending = {d["param"]: d for d in pending_disagreements(state)}
    if pending:
        focus_now = upd.get("focus_params", memo.focus_params)
        fixed = []
        for f in focus_now:
            d = pending.get(f.name)
            if d is None or f.locked or f.direction == d["cad"]:
                if d is not None:
                    how = "locked" if f.locked else "adopted"
                    events.append({"node": "chief_plan", "gen": gen, "event": f"chief_{how}_direction"} | d)
                fixed.append(f)
                continue
            if f.direction == d["chief"]:
                g = f.model_copy(update={"locked": True})
                how = "locked (restated without a lock)"
            else:
                g = f.model_copy(update={"direction": d["cad"], "locked": False})
                how = "adopted the CAD direction (was free)"
            events.append({"node": "chief_plan", "gen": gen, "event": "deadlock_coerced", "resolution": how} | d)
            fixed.append(g)
        if fixed != list(focus_now):
            upd["focus_params"] = fixed
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
        elif rec.screen is not None and not rec.screen.ok and rec.result.fidelity == "neuralfoil":
            ev = {"node": "chief_plan", "gen": gen, "cid": memo.promote_cid, "reasons": rec.screen.reasons()}
            reason = memo.screen_override.strip()
            ok, why = override_allowed(state, rec.result) if reason else (False, "")
            if ok:
                # The Chief may overrule the screen for a promotion (capped, in-box only); XFoil decides.
                events.append(ev | {"event": "promotion_screen_override", "reason": reason})
            else:
                if reason:
                    refused = {"event": "screen_override_refused", "kind": "promotion", "reason": reason, "why": why}
                    events.append(ev | refused)
                    upd["screen_override"] = ""
                # The NeuralFoil screen gates promotion; the generation explores at NeuralFoil instead.
                events.append(ev | {"event": "promotion_blocked_by_screen"})
                upd["promote_cid"], upd["fidelity"] = None, "neuralfoil"
    return (memo.model_copy(update=upd) if upd else memo), events
