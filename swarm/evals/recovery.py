"""XFoil recovery-ladder statistics from a run's ledger (milestone 2).

Every number comes from ledger records, never from events or agent text:
- a design-point XFoil solve is a record whose result is XFoil, or a NeuralFoil fallback with
  `fallback_from="xfoil"` (the ladder was exhausted). Levels are tried in order from L0, each once
  (`xfoil.next_level`), so a result at level k means levels 0..k-1 failed;
- a stall-probe point is one entry of `stall_margin.levels` after the design point; `None` there means the
  probe's own ladder was exhausted.
"""

from __future__ import annotations

from collections.abc import Iterable

from swarm.solvers.xfoil import LEVEL_NAMES, MAX_LEVEL
from swarm.state import EvalRecord


def _blank() -> dict:
    return {"solves": 0, "by_level": dict.fromkeys(range(MAX_LEVEL + 1), 0), "exhausted": 0, "unresolved": 0}


def _finish(s: dict) -> dict:
    """recovered = needed a level above L0 and converged; recovery_rate = recovered / (L0 failures)."""
    s["first_try"] = s["by_level"][0]
    s["recovered"] = sum(n for lvl, n in s["by_level"].items() if lvl > 0)
    failed_l0 = s["recovered"] + s["exhausted"]
    s["l0_failures"] = failed_l0
    s["recovery_rate"] = s["recovered"] / failed_l0 if failed_l0 else None
    return s


def ladder_stats(ledger: Iterable[EvalRecord]) -> dict[str, dict]:
    """{"design": ..., "probe": ...}: XFoil solves by the ladder level that produced them."""
    design, probe = _blank(), _blank()
    for rec in ledger:
        r = rec.result
        if r.fidelity == "xfoil":
            design["solves"] += 1
            if r.status == "converged" and r.solver_level is not None:
                design["by_level"][r.solver_level] += 1
            else:  # e.g. a node error left a failed XFoil result in the ledger
                design["unresolved"] += 1
        elif r.fallback_from == "xfoil":
            design["solves"] += 1
            design["exhausted"] += 1
        sm = rec.stall_margin
        if sm is not None:
            for lvl in sm.levels[1:]:
                probe["solves"] += 1
                if lvl is None:
                    probe["exhausted"] += 1
                else:
                    probe["by_level"][lvl] += 1
    return {"design": _finish(design), "probe": _finish(probe)}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.0f}%"


def report_section(ledger: list[EvalRecord]) -> list[str]:
    """Markdown lines for the run report; empty when the run made no XFoil solve."""
    st = ladder_stats(ledger)
    if not st["design"]["solves"] and not st["probe"]["solves"]:
        return []
    levels = range(MAX_LEVEL + 1)
    out = [
        "## XFoil recovery ladder",
        "",
        "| solves | n | "
        + " | ".join(f"L{k} {LEVEL_NAMES[k]}" for k in levels)
        + " | exhausted | recovered / L0 failures |",
        "|---|---|" + "---|" * len(levels) + "---|---|",
    ]
    for name, label in (("design", "design point"), ("probe", "stall probe (alpha+1, +2)")):
        s = st[name]
        cells = " | ".join(str(s["by_level"][k]) for k in levels)
        rate = f"{s['recovered']} / {s['l0_failures']} ({_pct(s['recovery_rate'])})"
        out.append(f"| {label} | {s['solves']} | {cells} | {s['exhausted']} | {rate} |")
    if st["design"]["unresolved"]:
        out.append(f"\n{st['design']['unresolved']} XFoil record(s) with no converged result and no fallback.")
    out += [
        "",
        "Level k = the ladder level that produced the result (levels below it failed). Exhausted: every level "
        "failed; a design-point solve then falls back to NeuralFoil (lower fidelity), a probe point leaves the "
        "stall margin unknown. From ledger.jsonl.",
        "",
    ]
    return out
