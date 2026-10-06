"""Inner-optimizer run summaries for the Chief brief and the report (no heavy imports)."""

from __future__ import annotations

INNER_BUDGET_MIN = 3
INNER_BUDGET_MAX = 12
INNER_BUDGET_DEFAULT = 8
INNER_RESERVE = 1  # evaluations an inner run leaves unused at the end of the budget (for a promotion)


def clamp_budget(k: int) -> int:
    """The inner budget actually used: 0 means the default; otherwise clamped to [MIN, MAX]."""
    return INNER_BUDGET_DEFAULT if k <= 0 else max(INNER_BUDGET_MIN, min(INNER_BUDGET_MAX, k))


def inner_runs(events: list[dict]) -> list[dict]:
    """The `inner_optimizer_finished` summaries of a run, in order."""
    return [e for e in events if e.get("event") == "inner_optimizer_finished"]


def inner_run_text(e: dict) -> str:
    """One line per inner run for the Chief brief and the report (ledger numbers only)."""
    box = ", ".join(f"{n} [{a:g}, {b:g}]" for n, (a, b) in e["box"].items()) or "(empty)"
    s = f"gen {e['gen']}: TPE over {box} around {e['parent_cid']}"
    if "warm_trials" in e:
        s += f" ({e['warm_trials']} warm-start design(s) from the ledger)"
    s += f"; {e['evals']} of {e['budget']} evaluations (stopped: {e['stopped']})"
    if e.get("rejected_geometry") or e.get("repeats"):
        s += f"; {e.get('rejected_geometry', 0)} geometry-infeasible and {e.get('repeats', 0)} repeated proposals"
    b = e.get("best")
    if b:
        cl = "n/a" if b["cl"] is None else f"{b['cl']:.4f}"
        cd = "n/a" if b["cd"] is None else f"{b['cd']:.5f}"
        v = b["violation"]
        vs = ", ".join(f"{k} {v[k]:.2f}" if v[k] is not None else f"{k} n/a" for k in ("stall", "separation", "box"))
        screen = {True: "screen ok", False: "screen failed", None: "not screened"}[b["screen_ok"]]
        s += f". Best {b['cid']}: Cl {cl}, Cd {cd}, {b['status']}, {screen}, violation {vs}"
        if e.get("parent_value") is not None:
            s += f" (value {b['value']:.3f} vs base {e['parent_value']:.3f})"
        s += f". In the target box: {', '.join(e['in_target_box']) or 'none'}"
        s += f". Promotable now: {', '.join(e['promotable']) or 'none'}"
    return s
