"""Screen overrides: when the Chief may send a screen-failed design to XFoil, and how they went.

The NeuralFoil screen gates XFoil. The Chief may overrule it with a logged `screen_override` reason,
at most MAX_SCREEN_OVERRIDES times per run and only for a design whose NeuralFoil result is inside
the target box (|Cl - target| <= cl_tol and Cd <= cd_max), not merely within the 2*tol promotion
window. Events: `promotion_screen_override` / `screen_override` (used), `screen_override_refused`.
The track record (each override and what XFoil found) is shown in every Chief brief.
"""

from __future__ import annotations

import math

from swarm.ledger import failing_checks, passing
from swarm.state import TERMINAL_FIDELITIES, CFDResult, DesignSpec, EvalRecord, SwarmState

MAX_SCREEN_OVERRIDES = 2
USED = ("promotion_screen_override", "screen_override")


def in_box(result: CFDResult | None, spec: DesignSpec) -> bool:
    if result is None or result.cl is None or result.cd is None:
        return False
    if not (math.isfinite(result.cl) and math.isfinite(result.cd)):
        return False
    return abs(result.cl - spec.target_cl) <= spec.cl_tol and result.cd <= spec.cd_max


def overrides_used(state: SwarmState) -> list[dict]:
    return [e for e in state.get("events", []) if e.get("event") in USED]


def override_allowed(state: SwarmState, nf: CFDResult | None) -> tuple[bool, str]:
    """(allowed, why not) for one more override of the design whose NeuralFoil result is `nf`."""
    spec = state["spec"]
    used = len(overrides_used(state))
    if used >= MAX_SCREEN_OVERRIDES:
        return False, f"override cap reached ({used} of {MAX_SCREEN_OVERRIDES} used this run)"
    if not in_box(nf, spec):
        nums = f"Cl {nf.cl:.4f}, Cd {nf.cd:.5f}" if nf is not None and nf.cl is not None and nf.cd else "no result"
        return False, (
            f"NeuralFoil result not inside the target box ({nums}; box Cl {spec.target_cl} ± {spec.cl_tol}, "
            f"Cd ≤ {spec.cd_max})"
        )
    return True, ""


def outcome(cid: str, ledger: list[EvalRecord], spec: DesignSpec) -> str:
    """What the authoritative tier found for an overridden design (ledger facts only)."""
    recs = [r for r in ledger if r.params.cid == cid and r.result.fidelity in TERMINAL_FIDELITIES]
    if not recs:
        return "not evaluated at XFoil yet"
    r = recs[-1]
    res = r.result
    nums = f"Cl {res.cl:.4f}, Cd {res.cd:.5f}" if res.cl is not None and res.cd is not None else res.status
    if passing(r):
        return f"XFoil PASS ({nums}): the screen was wrong here"
    why = (failing_checks(r, spec) or ["not a pass"])[0]
    if r.stall_untested:
        return f"XFoil fail ({nums}): {why}; stall untested (probe not run): no evidence about the screen"
    return f"XFoil fail ({nums}): {why}"


def track_record(state: SwarmState) -> list[dict]:
    """Every override used or refused this run, with its outcome."""
    spec, ledger = state["spec"], state.get("ledger", [])
    out = []
    for e in state.get("events", []):
        ev = e.get("event")
        if ev in USED:
            kind = "promotion" if ev == "promotion_screen_override" else "direct to XFoil"
            out.append({"gen": e["gen"], "cid": e["cid"], "kind": kind, "outcome": outcome(e["cid"], ledger, spec)})
        elif ev == "screen_override_refused":
            out.append({"gen": e["gen"], "cid": e["cid"], "kind": e["kind"], "outcome": f"refused: {e['why']}"})
    return out


def track_record_text(state: SwarmState) -> str:
    rec = track_record(state)
    used = len(overrides_used(state))
    head = (
        f"Used {used} of {MAX_SCREEN_OVERRIDES}; allowed only for a design whose NeuralFoil result is inside "
        "the target box."
    )
    if not rec:
        return head + "\n(none yet)"
    return head + "\n" + "\n".join(f"- gen {r['gen']} {r['kind']} of {r['cid']}: {r['outcome']}" for r in rec)
