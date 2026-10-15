"""XFoil failure zoo (milestone 2): stress cases for the recovery ladder, and what the ladder does with them.

Every case is solved at every ladder level (not only until the first converged one), so the zoo measures
two things:
- recovery: which level the graph's ladder (L0, then the next untried level, `xfoil.next_level`) would
  accept, how often a level above L0 recovers a failed solve, and how often the ladder is exhausted;
- agreement: whether the levels that converge give the same answer. The ladder accepts the first
  converged level, so a spread between levels is a silent error in the accepted result. Two kinds:
  "branch" (another level with the same panel count converged to a different solution, e.g. alpha
  continuation reaching another branch of the polar) and "panels" (L3's 240 panels against 160: the
  discretization error of the accepted result).

Cases are labelled by the stress they apply (category); the outcome is measured, not assumed. Results are
cached in evals/xfoil_zoo.json (`scripts/failure_zoo.py run`) so tests and the report need no XFoil.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable

from swarm.cad.regulations import min_thickness_for_le_radius
from swarm.solvers.xfoil import LEVEL_NAMES, LEVELS, MAX_LEVEL
from swarm.state import PLACEHOLDER_CAR, CFDResult, WingParams

# Converged levels whose Cl differ by more than this disagree (the hard target's tolerance is 0.03).
DISAGREE_TOL = 0.02

# category -> (description, grid of (camber, camber_pos, thickness, alpha))
CATEGORIES: dict[str, tuple[str, list[tuple[float, float, float, float]]]] = {
    "thin_high_alpha": (
        "thin sections (below the FSAE 2027 LE-radius minimum) at high alpha",
        list(itertools.product([0.0, 0.02, 0.04, 0.06], [0.4], [0.08, 0.10], [9.0, 11.0, 13.0, 14.0])),
    ),
    "fsae_high_alpha": (
        "FSAE-legal sections near and past Cl,max",
        list(itertools.product([0.06, 0.09], [0.4], [0.123, 0.13], [12.0, 13.0, 14.0])),
    ),
    "aft_camber": (
        "high camber far aft (strong TE loading, early TE separation)",
        list(itertools.product([0.07, 0.09], [0.55, 0.6], [0.13], [8.0, 11.0, 14.0])),
    ),
    "thick_high_alpha": (
        "thick sections at high alpha (TE separation creeping forward)",
        list(itertools.product([0.0, 0.04], [0.4], [0.16, 0.18], [11.0, 14.0])),
    ),
    "near_target": (
        "the hard preset's target region (control: where runs promote designs)",
        list(itertools.product([0.08, 0.09], [0.35, 0.4], [0.135], [8.75, 9.5])),
    ),
    "low_alpha": (
        "low and negative alpha (control: attached flow)",
        list(itertools.product([0.0, 0.06], [0.4], [0.13], [-2.0, 0.0, 3.0])),
    ),
}


def cases() -> list[dict]:
    """Deterministic case list: {name, category, params}."""
    out = []
    for cat, (_, grid) in CATEGORIES.items():
        for m, p, t, a in grid:
            params = WingParams(main_camber=m, main_camber_pos=p, main_thickness=t, alpha_deg=a)
            out.append({"name": f"{cat}/m{m:g}_p{p:g}_t{t:g}_a{a:g}", "category": cat, "params": params})
    return out


def fsae_legal(params: WingParams) -> bool:
    return params.main_thickness >= min_thickness_for_le_radius(PLACEHOLDER_CAR.chord_mm) - 1e-9


def _level_row(r: CFDResult) -> dict:
    ok = r.status == "converged" and r.cl is not None and math.isfinite(r.cl)
    return {
        "level": r.solver_level,
        "status": "converged" if ok else r.status,
        "signature": None if ok else (r.failure_signature or r.status),
        "cl": r.cl if ok else None,
        "cd": r.cd if ok else None,
        "te_sep_xc": r.bl.te_separation_xc if ok and r.bl else None,
        "wall_s": round(r.wall_s, 3),
    }


def run_case(
    case: dict, solve: Callable[[WingParams, int], CFDResult], reference: Callable[[WingParams], CFDResult]
) -> dict:
    """Solve the case at every ladder level; `reference` is the NeuralFoil result (not ground truth)."""
    p: WingParams = case["params"]
    ref = reference(p)
    return {
        "name": case["name"],
        "category": case["category"],
        "params": p.model_dump(),
        "fsae_legal": fsae_legal(p),
        "neuralfoil": {"cl": ref.cl, "cd": ref.cd, "confidence": ref.confidence},
        "levels": [_level_row(solve(p, lvl)) for lvl in range(MAX_LEVEL + 1)],
    }


def outcome(res: dict) -> dict:
    """What the graph's ladder would do with this case, and how much the converged levels disagree."""
    conv = [x for x in res["levels"] if x["status"] == "converged"]
    accepted = conv[0] if conv else None
    branch_dev = panel_dev = 0.0
    if accepted:
        # how far another converged level is from the accepted answer, at the same / another panel count
        npanel = LEVELS[accepted["level"]]["npanel"]
        for x in conv:
            d = abs(x["cl"] - accepted["cl"])
            if LEVELS[x["level"]]["npanel"] == npanel:
                branch_dev = max(branch_dev, d)
            else:
                panel_dev = max(panel_dev, d)
    return {
        "accepted_level": accepted["level"] if accepted else None,
        "accepted_cl": accepted["cl"] if accepted else None,
        "exhausted": accepted is None,
        "converged_levels": [x["level"] for x in conv],
        "branch_deviation": branch_dev,
        "panel_deviation": panel_dev,
        "branch": branch_dev > DISAGREE_TOL,
        "panels": panel_dev > DISAGREE_TOL,
        "first_signature": res["levels"][0]["signature"],
    }


def label(o: dict) -> str:
    if o["exhausted"]:
        return "exhausted"
    base = "clean" if o["accepted_level"] == 0 else f"recovered@L{o['accepted_level']}"
    return base + (" + branch" if o["branch"] else "") + (" + panels" if o["panels"] else "")


def summarize(results: list[dict]) -> dict:
    outs = [outcome(r) for r in results]
    n_levels = MAX_LEVEL + 1
    # conditional recovery: of the cases that reach level k (all lower levels failed), how many converge at k
    per_level = []
    for k in range(n_levels):
        reach = [r for r in results if all(x["status"] != "converged" for x in r["levels"][:k])]
        conv = [r for r in reach if r["levels"][k]["status"] == "converged"]
        per_level.append({"level": k, "name": LEVEL_NAMES[k], "attempts": len(reach), "converged": len(conv)})
    by_cat: dict[str, dict] = {}
    for r, o in zip(results, outs, strict=True):
        c = by_cat.setdefault(
            r["category"],
            {"cases": 0, "fsae_legal": 0, "clean": 0, "recovered": 0, "exhausted": 0, "branch": 0, "panels": 0},
        )
        c["cases"] += 1
        c["fsae_legal"] += r["fsae_legal"]
        c["exhausted"] += o["exhausted"]
        c["clean"] += o["accepted_level"] == 0
        c["recovered"] += bool(o["accepted_level"])
        c["branch"] += o["branch"]
        c["panels"] += o["panels"]
    l0_failed = sum(o["accepted_level"] != 0 for o in outs)
    recovered = sum(bool(o["accepted_level"]) for o in outs)
    return {
        "cases": len(results),
        "l0_failures": l0_failed,
        "recovered": recovered,
        "exhausted": sum(o["exhausted"] for o in outs),
        "recovery_rate": recovered / l0_failed if l0_failed else None,
        "branch": sum(o["branch"] for o in outs),
        "panels": sum(o["panels"] for o in outs),
        "per_level": per_level,
        "by_category": by_cat,
        "outcomes": outs,
    }


def _f(x: float | None, fmt: str = "{:.3f}") -> str:
    return "—" if x is None else fmt.format(x)


def markdown(results: list[dict], meta: dict) -> str:
    s = summarize(results)
    rate = "n/a" if s["recovery_rate"] is None else f"{100 * s['recovery_rate']:.0f}%"
    legal = summarize([r for r in results if r["fsae_legal"]])
    out = [
        "# XFoil failure zoo",
        "",
        f"Generated by `scripts/failure_zoo.py report` from `evals/xfoil_zoo.json` (XFoil run {meta.get('date', '?')}, "
        f"Re {meta.get('reynolds', 0):.3e}, Ncrit {meta.get('ncrit', '?')}). Every case is solved at every ladder "
        "level; the graph's ladder accepts the first level that converges. Negative Cl = downforce. "
        f"Levels disagree when a converged level's Cl is more than {DISAGREE_TOL} from the accepted one: "
        "branch = at the same panel count (another solution), panels = L3's 240 panels against 160. "
        "NeuralFoil is listed for reference; it is not ground truth.",
        "",
        "## Summary",
        "",
        f"- {s['cases']} cases; L0 failed on {s['l0_failures']}; the ladder recovered {s['recovered']} "
        f"({rate}) and was exhausted on {s['exhausted']}.",
        f"- FSAE-legal cases (the search domain): {legal['cases']}; L0 failed on {legal['l0_failures']}, recovered "
        f"{legal['recovered']}, exhausted {legal['exhausted']}.",
        f"- The accepted result disagreed with another converged level: branch {s['branch']}, panels "
        f"{s['panels']} case(s).",
        "",
        "| level | action | cases reaching it | converged there |",
        "|---|---|---|---|",
    ]
    out += [f"| L{x['level']} | {x['name']} | {x['attempts']} | {x['converged']} |" for x in s["per_level"]]
    out += [
        "",
        "| category | what it stresses | cases (FSAE-legal) | clean at L0 | recovered | exhausted | branch | panels |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cat, c in s["by_category"].items():
        out.append(
            f"| {cat} | {CATEGORIES[cat][0] if cat in CATEGORIES else ''} | {c['cases']} ({c['fsae_legal']}) "
            f"| {c['clean']} | {c['recovered']} | {c['exhausted']} | {c['branch']} | {c['panels']} |"
        )
    out += [
        "",
        "## Cases",
        "",
        "| case | FSAE | label | L0 | L1 | L2 | L3 | NeuralFoil Cl | accepted − NF |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r, o in zip(results, s["outcomes"], strict=True):
        cells = []
        for x in r["levels"]:
            if x["status"] == "converged":
                sep = "" if x["te_sep_xc"] is None else f" sep {x['te_sep_xc']:.2f}"
                cells.append(f"{x['cl']:.3f}{sep}")
            else:
                cells.append(f"✗ {x['signature']}")
        nf = r["neuralfoil"]["cl"]
        diff = None if o["accepted_cl"] is None or nf is None else o["accepted_cl"] - nf
        out.append(
            f"| {r['name']} | {'yes' if r['fsae_legal'] else 'no'} | {label(o)} | "
            + " | ".join(cells)
            + f" | {_f(nf)} | {_f(diff, '{:+.3f}')} |"
        )
    out += [
        "",
        "Cells: Cl at that level (sep x = TE separation from x/c, from XFoil's boundary layer), or ✗ and the "
        "failure signature. Levels: " + ", ".join(f"L{k} {v}" for k, v in LEVEL_NAMES.items()) + ".",
        "",
    ]
    return "\n".join(out)
