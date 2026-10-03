"""Plateau policy: a declared plateau ends the run only late in the evaluation budget.

Before PLATEAU_MIN_FRACTION of max_evals is used, `declare_plateau` is turned into exploration,
alternating between two moves (logged as `plateau_deferred`):

- widen: a larger trust region (at least WIDEN_RADIUS of each range) and the focus padded with
  the other free parameters;
- restart: the CAD base moves to a different region of the ledger (the least-violating design at
  least RESTART_DISTANCE of the range away from the current base and earlier restart anchors),
  directions free. For RESTART_GENERATIONS generations the base is the best design of that branch
  (the anchor plus designs first evaluated since the restart), then normal parent selection resumes.

Deterministic: the Chief only sets the flag.
"""

from __future__ import annotations

import math

from swarm.ledger import latest_per_cid, objective, select_parent, violation
from swarm.state import DesignSpec, EvalRecord, FocusParam, StrategyMemo, SwarmState, WingParams, free_params

PLATEAU_MIN_FRACTION = 0.8
WIDEN_RADIUS = 0.3
RESTART_RADIUS = 0.15
RESTART_DISTANCE = 0.2
RESTART_GENERATIONS = 3


def plateau_allowed_after(spec: DesignSpec) -> int:
    """Evaluations after which a declared plateau may end the run."""
    return math.ceil(PLATEAU_MIN_FRACTION * spec.max_evals)


def plateau_allowed(state: SwarmState) -> bool:
    return len(state.get("ledger", [])) >= plateau_allowed_after(state["spec"])


def distance(a: WingParams, b: WingParams, names: list[str]) -> float:
    """Largest change over `names`, as a fraction of each parameter's range."""
    bounds = WingParams.bounds()
    return max((abs(getattr(a, n) - getattr(b, n)) / (bounds[n][1] - bounds[n][0]) for n in names), default=0.0)


def _deferrals(state: SwarmState) -> list[dict]:
    return [e for e in state.get("events", []) if e.get("event") == "plateau_deferred"]


def active_branch(state: SwarmState) -> dict | None:
    """The restart branch in force at the state's generation, if any."""
    ex = state.get("exploration")
    gen = state.get("generation", 0)
    return ex if ex and ex["from_gen"] <= gen <= ex["until_gen"] else None


def branch_cids(ledger: list[EvalRecord], branch: dict) -> set[str]:
    """The anchor plus every design first evaluated at or after the restart generation."""
    first: dict[str, int] = {}
    for r in ledger:
        first.setdefault(r.params.cid, r.generation)
    return {branch["anchor_cid"]} | {c for c, g in first.items() if g >= branch["from_gen"]}


def current_parent(state: SwarmState) -> tuple[EvalRecord | None, str]:
    """`ledger.select_parent`, restricted to the restart branch while one is active."""
    ledger, spec = state.get("ledger", []), state["spec"]
    br = active_branch(state)
    if br is None:
        return select_parent(ledger, spec)
    cids = branch_cids(ledger, br)
    rec, why = select_parent([r for r in ledger if r.params.cid in cids], spec)
    if rec is None:
        return select_parent(ledger, spec)
    return rec, f"restart branch from {br['anchor_cid']} (gens {br['from_gen']}–{br['until_gen']}): {why}"


def restart_anchor(
    ledger: list[EvalRecord], spec: DesignSpec, avoid: list[WingParams]
) -> tuple[EvalRecord | None, str]:
    """The least-violating design at least RESTART_DISTANCE from every design in `avoid`; if there
    is none, the design farthest from them."""
    names = list(free_params(spec))
    avoid_cids = {a.cid for a in avoid}
    rows = [r for r in latest_per_cid(ledger) if r.params.cid not in avoid_cids]
    if not rows:
        return None, "no other evaluated design"

    def gap(r: EvalRecord) -> float:
        return min((distance(r.params, a, names) for a in avoid), default=1.0)

    far = [r for r in rows if gap(r) >= RESTART_DISTANCE]
    if far:
        best = min(far, key=lambda r: (violation(r, spec)["total"], objective(r.result, spec)))
        return best, f"least constraint violation at >= {RESTART_DISTANCE} of range from the current base"
    best = max(rows, key=gap)
    return best, f"farthest design ({gap(best):.2f} of range; none at >= {RESTART_DISTANCE})"


def _pad_focus(focus: list[FocusParam], spec: DesignSpec, free_dirs: bool) -> list[FocusParam]:
    focus = [FocusParam(name=f) if isinstance(f, str) else f for f in focus]  # model_copy skips validators
    out = [FocusParam(name=f.name) if free_dirs else f for f in focus]
    names = {f.name for f in out}
    out += [FocusParam(name=n) for n in free_params(spec) if n not in names]
    return out[:3]


def handle_plateau(
    memo: StrategyMemo, state: SwarmState, parent: WingParams | None
) -> tuple[StrategyMemo, list[dict], dict | None]:
    """Apply the plateau policy to a sanitized memo. Returns (memo, events, new restart branch).

    `state` carries the generation being planned; `parent` is the base `current_parent` chose.
    """
    if not memo.declare_plateau or plateau_allowed(state):
        return memo, [], None
    spec, ledger = state["spec"], state.get("ledger", [])
    gen = state.get("generation", 0)
    ev = {
        "node": "chief_plan",
        "gen": gen,
        "event": "plateau_deferred",
        "evals": len(ledger),
        "allowed_after": plateau_allowed_after(spec),
    }
    upd: dict = {"declare_plateau": False}
    if memo.promote_cid:  # the promotion is this generation's move; no CAD step to widen
        return memo.model_copy(update=upd), [ev | {"action": "promotion", "cid": memo.promote_cid}], None
    prev = _deferrals(state)
    action = "restart" if prev and prev[-1]["action"] == "widen" else "widen"
    branch = None
    if action == "restart":
        anchors = [e["anchor_cid"] for e in prev if e["action"] == "restart"]
        by_cid = {r.params.cid: r.params for r in ledger}
        avoid = ([parent] if parent else []) + [by_cid[c] for c in anchors if c in by_cid]
        rec, why = restart_anchor(ledger, spec, avoid)
        if rec is None:
            action = "widen"
            ev["restart_skipped"] = why
        else:
            radius = min(0.5, max(memo.trust_radius, RESTART_RADIUS))
            upd |= {"trust_radius": radius, "focus_params": _pad_focus(memo.focus_params, spec, free_dirs=True)}
            branch = {"anchor_cid": rec.params.cid, "from_gen": gen, "until_gen": gen + RESTART_GENERATIONS - 1}
            ev |= {
                "action": "restart",
                "anchor_cid": rec.params.cid,
                "from_cid": parent.cid if parent else None,
                "why": why,
                "until_gen": branch["until_gen"],
                "trust_radius": [memo.trust_radius, radius],
            }
    if action == "widen":
        radius = min(0.5, max(WIDEN_RADIUS, 2 * memo.trust_radius))
        upd |= {"trust_radius": radius, "focus_params": _pad_focus(memo.focus_params, spec, free_dirs=False)}
        ev |= {"action": "widen", "trust_radius": [memo.trust_radius, radius]}
    new = memo.model_copy(update=upd)
    ev["focus"] = [f.model_dump() for f in new.focus_params]
    return new, [ev], branch
