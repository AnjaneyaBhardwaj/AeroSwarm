"""Per-role context builders: `brief_for(role, state, ...)`.

Each LLM node builds its prompt fresh from state. No agent reads another
agent's prose; the only cross-agent channel is typed data (diagnosis enums,
ledger numbers, violations).

A brief is (system, user, facts). `user` is what the model reads; `facts` is
the same information as a dict, used by the deterministic MockClient so it
sees exactly what the model would see.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from swarm.cad.apply import allowed_interval
from swarm.cad.heuristics import lookup_heuristics
from swarm.explore import active_branch, current_parent, plateau_allowed_after
from swarm.ledger import (
    best_record,
    dial_coverage,
    dial_coverage_table,
    failing_checks,
    markdown_table,
    no_improve_streak,
    objective,
    passing,
    row,
    usable,
)
from swarm.optim.summary import INNER_BUDGET_DEFAULT, INNER_BUDGET_MAX, INNER_BUDGET_MIN, inner_run_text, inner_runs
from swarm.overrides import MAX_SCREEN_OVERRIDES, in_box, overrides_used, track_record, track_record_text
from swarm.state import (
    FIDELITY_RANK,
    DesignSpec,
    EvalRecord,
    StrategyMemo,
    SwarmState,
    WingParams,
    free_params,
)

PROMPTS = Path(__file__).parent / "agents" / "prompts"
NEAR_TARGET_FACTOR = 2.0  # a candidate within 2·tol is worth promoting


@dataclass
class Brief:
    system: str
    user: str
    facts: dict


def _system(role: str, spec: DesignSpec, **extra: str) -> str:
    tpl = (PROMPTS / f"{role}.md").read_text()
    return tpl.format(
        **extra,
        component=spec.component,
        target_cl=spec.target_cl,
        cl_tol=spec.cl_tol,
        cd_max=spec.cd_max,
        reynolds=spec.reynolds,
        chord_mm=spec.car.chord_mm,
        speed_mps=spec.speed_mps,
    )


def _spec_block(spec: DesignSpec) -> str:
    return "## DesignSpec (immutable)\n```json\n" + spec.model_dump_json(indent=1) + "\n```"


def screen_blocked(rec: EvalRecord) -> bool:
    """A NeuralFoil result whose screen failed may not be promoted to XFoil."""
    return rec.result.fidelity == "neuralfoil" and rec.screen is not None and not rec.screen.ok


def near_target(ledger: list[EvalRecord], spec: DesignSpec, to: str = "xfoil") -> list[EvalRecord]:
    """Lower-tier candidates within NEAR_TARGET_FACTOR·tol and under cd_max, not yet run at `to`."""
    done = {(r.params.cid, r.result.fidelity) for r in ledger}
    # a fallback record means the higher tier was already attempted and failed
    done |= {(r.params.cid, r.result.fallback_from) for r in ledger if r.result.fallback_from}
    out = []
    for r in ledger:
        res = r.result
        if not usable(r) or FIDELITY_RANK[res.fidelity] >= FIDELITY_RANK[to] or (r.params.cid, to) in done:
            continue
        if abs(res.cl - spec.target_cl) <= NEAR_TARGET_FACTOR * spec.cl_tol and res.cd <= spec.cd_max:
            out.append(r)
    return sorted(out, key=lambda r: objective(r.result, spec))


def promotable(ledger: list[EvalRecord], spec: DesignSpec, to: str = "xfoil") -> list[EvalRecord]:
    return [r for r in near_target(ledger, spec, to) if not screen_blocked(r)]


def chief_brief(state: SwarmState, sens: dict) -> Brief:
    spec, ledger = state["spec"], state.get("ledger", [])
    rows = [row(r, spec) for r in ledger]
    best5 = sorted([x for x in rows if x["objective"] is not None], key=lambda x: x["objective"])[:5]
    last5 = rows[-5:]
    fails = [
        x
        for x in rows
        if x["quarantined"] or x["status"] in ("NON_PHYSICAL", "NUMERICAL_FAILURE") or x["lower_fidelity"]
    ]
    best = best_record(ledger, spec)
    best_x = best_record(ledger, spec, "xfoil")
    v = state.get("verdict")
    # the Critic's verdict belongs to the last agent-evaluated record (inner-optimizer records have no Critic call)
    v_rec = next((r for r in reversed(ledger) if not r.inner_optimizer), None)
    parent, parent_why = current_parent(state)
    events = state.get("events", [])
    history = _history(state.get("history", []), ledger, spec, events)
    overrides = pending_disagreements(state)
    cols = ("gen", "cid", "by", "fidelity", "status", "cl", "cd", "objective", "failing", "stall_probe")
    inner_allowed = bool(state.get("inner_allowed", False))
    inner = inner_runs(events)
    promo = [r.params.cid for r in promotable(ledger, spec)]
    blocked = {
        r.params.cid: r.screen.reasons()
        + ["inside the target box: override allowed" if in_box(r.result, spec) else "outside the box: no override"]
        for r in sorted(near_target(ledger, spec), key=lambda r: r.generation)
        if screen_blocked(r)
    }
    used = len(overrides_used(state))
    streak = no_improve_streak(ledger, spec)
    coverage = dial_coverage(ledger, list(free_params(spec)))
    facts = {
        "spec": spec.model_dump(),
        "free_params": list(free_params(spec)),
        "generation": state.get("generation", 0),
        "evals_used": len(ledger),
        "best": row(best, spec) if best else None,
        "best_xfoil": row(best_x, spec) if best_x else None,
        "recent": last5,
        "failures": fails[-10:],
        "sensitivities": sens,
        "verdict": v.model_dump() if v else None,
        "promotable": promo,
        "screen_blocked": blocked,
        "no_improve_streak": streak,
        "last_strategy": state["strategy"].model_dump() if state.get("strategy") else None,
        "parent": {"cid": parent.params.cid, "why": parent_why} if parent else None,
        "history": history,
        "cad_overrides": overrides,
        "dial_coverage": coverage,
        "screen_overrides": track_record(state),
        "screen_overrides_left": max(0, MAX_SCREEN_OVERRIDES - used),
        "plateau_allowed_after": plateau_allowed_after(spec),
        "restart_branch": active_branch(state),
        "inner_optimizer": {
            "allowed": inner_allowed,
            "budget_min": INNER_BUDGET_MIN,
            "budget_max": INNER_BUDGET_MAX,
            "budget_default": INNER_BUDGET_DEFAULT,
            "runs": inner[-INNER_RUNS_SHOWN:],
        },
    }
    user = "\n\n".join(
        [
            _spec_block(spec),
            f"Generation {facts['generation']}; evaluations used {len(ledger)} of {spec.max_evals}. "
            f"Free parameters: {', '.join(facts['free_params'])}.",
            "## Best 5 (lowest objective = |Cl−target| + 20·max(0, Cd−cd_max))\n" + markdown_table(best5, cols),
            "## Last 5\n" + markdown_table(last5, cols),
            "## Failure table\n" + markdown_table(fails[-10:], cols),
            "## Next CAD base (the design your focus_params will modify)\n"
            + (
                f"{parent.params.cid}: {parent_why}\n{json.dumps(row(parent, spec)['params'])}"
                if parent
                else "(the start design)"
            ),
            "## Dial coverage (all evaluated designs; a move = a design whose value differs from its parent's)\n"
            + dial_coverage_table(coverage),
            "## Sensitivities at the CAD base (NeuralFoil; per unit parameter; race-car Cl)\n"
            + json.dumps(sens, indent=1),
            "## The CAD agent overrode your direction last generation (you must resolve each one)\n"
            + (
                "\n".join(
                    f"- {d['param']}: you said {_DIR_TEXT[d['chief']]}, CAD went {_DIR_TEXT[d['cad']]}: {d['reason']}"
                    for d in overrides
                )
                + "\nFor each parameter you keep in focus: adopt the CAD's direction, or keep yours with "
                "locked=true (the CAD then cannot override it). Or drop the parameter."
                if overrides
                else "(none)"
            ),
            "## Your previous hypotheses and what happened (from the ledger)\n"
            + ("\n".join(f"- gen {h['gen']}: {h['hypothesis']} -> {h['outcome']}" for h in history) or "(none yet)"),
            "## Critic's latest verdict"
            + (f" (gen {v_rec.generation}, {v_rec.params.cid})" if v and v_rec else "")
            + "\n"
            + (v.model_dump_json(indent=1) if v else "(none)"),
            f"## Promotion candidates (within {NEAR_TARGET_FACTOR}·tol at neuralfoil, not yet run at xfoil)\n"
            + (", ".join(promo) or "(none)"),
            "## Blocked from promotion by the NeuralFoil screen (alpha+1/+2 slope, suction-side TE H); "
            f"promote one only with screen_override = your reason ({max(0, MAX_SCREEN_OVERRIDES - used)} "
            "override(s) left, only for a design inside the target box)\n"
            + ("\n".join(f"- {cid}: {'; '.join(why)}" for cid, why in blocked.items()) or "(none)"),
            "## Your screen overrides this run and what XFoil found\n" + track_record_text(state),
            "## Inner-optimizer runs (deterministic TPE at NeuralFoil inside your focus subspace; ledger numbers)\n"
            + (
                ("\n".join(f"- {inner_run_text(e)}" for e in inner[-INNER_RUNS_SHOWN:]) or "(none yet)")
                if inner_allowed or inner
                else "(disabled in this run)"
            ),
            f"Generations without improvement: {streak}. declare_plateau ends the run only after "
            f"{facts['plateau_allowed_after']} of {spec.max_evals} evaluations; before that it makes the run "
            "explore instead (alternately a wider trust region, or a restart from a different region of the "
            "ledger).",
        ]
    )
    return Brief(_system("chief", spec, mode_text=mode_text(inner_allowed)), user, facts)


INNER_RUNS_SHOWN = 3


def mode_text(inner_allowed: bool) -> str:
    """The Chief prompt's mode paragraph: the inner optimizer is a real choice only when the run allows it."""
    if not inner_allowed:
        return '"reasoned_step" (the inner optimizer is disabled in this run).'
    lines = [
        '"reasoned_step" or "inner_optimizer".',
        "   - reasoned_step: the CAD agent makes one reasoned change to the next CAD base (one",
        "     evaluation at the fidelity you choose).",
        "   - inner_optimizer: a deterministic optimizer (Optuna TPE, no LLM) spends inner_budget",
        f"     evaluations ({INNER_BUDGET_MIN}-{INNER_BUDGET_MAX}; 0 means {INNER_BUDGET_DEFAULT}) at neuralfoil, "
        "searching only your focus_params",
        '     within the trust region around the next CAD base (one-sided for a "+" or "-"',
        "     direction; other parameters stay at the base values), warm-started from ledger designs",
        "     in that region. It minimizes the constraint violation used to choose the CAD base",
        "     (stall shortfall, separation, distance outside the target box). The screen and",
        "     validator apply as usual; every inner evaluation is a ledger record and counts toward",
        "     the evaluation budget (it leaves the last evaluation of the run free). It never",
        "     promotes: your next brief shows what it found, and you decide promotions as usual.",
        "     fidelity is ignored for an inner run (always neuralfoil); a promotion (promote_cid)",
        "     takes precedence over it.",
    ]
    return "\n".join(lines)


_DIR_TEXT = {"+": "increase", "-": "decrease", "free": "free"}


def pending_disagreements(state: SwarmState) -> list[dict]:
    """CAD overrides of the Chief's direction in the generation of the Chief's previous memo."""
    hist = state.get("history", [])
    if not hist:
        return []
    gen = hist[-1]["gen"]
    out: dict[str, dict] = {}
    for e in state.get("events", []):
        if e.get("event") == "chief_cad_disagreement" and e.get("gen") == gen:
            out[e["param"]] = {k: e[k] for k in ("param", "chief", "cad", "reason")}
    return list(out.values())


HISTORY_SHOWN = 8


def _history(
    entries: list[dict], ledger: list[EvalRecord], spec: DesignSpec, events: list[dict] | None = None
) -> list[dict]:
    """The Chief's last memos with each generation's outcome taken from the ledger."""
    out = []
    inner = {e["gen"]: e for e in inner_runs(events or [])}
    for h in entries[-HISTORY_SHOWN:]:
        recs = [r for r in ledger if r.generation == h["gen"]]
        agent_recs = [r for r in recs if not r.inner_optimizer]
        if h["gen"] in inner and not agent_recs:
            outcome = "inner optimizer: " + inner_run_text(inner[h["gen"]]).split(": ", 1)[1]
        elif not recs:
            outcome = "no evaluation"
        else:
            r = recs[-1]
            res = r.result
            nums = f"Cl {res.cl:.4f} Cd {res.cd:.5f}" if res.cl is not None and res.cd is not None else res.status
            why = failing_checks(r, spec)
            status = "PASS (full)" if passing(r) else (r.verdict.status if r.verdict else res.status)
            outcome = f"{r.params.cid} at {res.fidelity}: {status}, {nums}" + (f"; failing: {why[0]}" if why else "")
            if r.stall_untested:
                outcome += "; stall untested (XFoil stall probe not run: no evidence about the screen)"
        if h.get("explore"):
            outcome = f"(plateau deferred: {h['explore']}) {outcome}"
        focus = ", ".join(f"{f['name']} {_DIR_TEXT[f['direction']]}" for f in h["focus"])
        out.append({"gen": h["gen"], "hypothesis": h["hypothesis"][:300], "focus": focus, "outcome": outcome})
    return out


def cad_brief(state: SwarmState, base: WingParams, base_rec: EvalRecord | None, sens: dict) -> Brief:
    spec, strat = state["spec"], state["strategy"]
    assert strat is not None
    # The diagnosis must describe the design being modified: the base's own record, never the
    # latest verdict (which belongs to whatever was evaluated last).
    v = base_rec.verdict if base_rec is not None and base_rec.params.cid == base.cid else None
    diag = v.diagnosis if v else None
    allowed = [p for p in strat.focus_names if p in free_params(spec)]
    directions = {p: strat.direction(p) for p in allowed}
    locked = {p for p in allowed if strat.locked(p)}
    why_not = failing_checks(base_rec, spec) if base_rec is not None else []
    bounds = WingParams.bounds()
    intervals = {p: allowed_interval(p, base, strat.trust_radius) for p in allowed}
    heur = [h.model_dump() for h in lookup_heuristics(diag.symptom, allowed)] if diag else []
    res = base_rec.result if base_rec else None
    facts = {
        "spec": spec.model_dump(),
        "generation": state.get("generation", 0),
        "base": base.model_dump(),
        "base_cid": base.cid,
        "base_result": {"cl": res.cl, "cd": res.cd, "fidelity": res.fidelity} if res else None,
        "base_failing": why_not,
        "focus_params": allowed,
        "directions": directions,
        "locked": sorted(locked),
        "trust_radius": strat.trust_radius,
        "bounds": {p: bounds[p] for p in allowed},
        "intervals": intervals,
        "sensitivities": {p: sens[p] for p in allowed if p in sens},
        "diagnosis": diag.model_dump() if diag else None,
        "diagnosis_cid": base_rec.params.cid if v is not None else None,
        "heuristics": heur,
        "pending_violation": state.get("pending_violation"),
        "cad_retries": state.get("retries", {}).get("cad", 0),
    }
    user = "\n\n".join(
        [
            _spec_block(spec),
            "## Current design (WingParams)\n```json\n" + base.model_dump_json(indent=1) + "\n```",
            "## Its result\n" + (json.dumps(facts["base_result"]) if res else "(not evaluated yet)"),
            "## Why it is not a pass\n" + ("\n".join(f"- {w}" for w in why_not) or "(it passed at its fidelity)"),
            f"## Allowed changes (trust radius {strat.trust_radius} of range) and the Chief's direction\n"
            + "\n".join(
                f"- {p}: bounds {bounds[p]}, allowed interval [{a:.4f}, {b:.4f}], Chief: {_DIR_TEXT[directions[p]]}"
                + (" (LOCKED: no override)" if p in locked else "")
                for p, (a, b) in intervals.items()
            ),
            "## Sensitivities (per unit change; race-car Cl, negative = more downforce)\n"
            + json.dumps(facts["sensitivities"], indent=1),
            f"## Critic diagnosis of this design ({base.cid})\n"
            + (diag.model_dump_json(indent=1) if diag else "(none)"),
            "## Heuristics for this symptom\n" + (json.dumps(heur, indent=1) if heur else "(none)"),
            "## Rejected previous proposal\n" + (state.get("pending_violation") or "(none)"),
        ]
    )
    return Brief(_system("cad", spec), user, facts)


def critic_brief(state: SwarmState, suggested, parent_rec: EvalRecord | None) -> Brief:
    spec, res, params, numeric = state["spec"], state["result"], state["params"], state["numeric"]
    parent = parent_rec.result if parent_rec else None
    facts = {
        "spec": spec.model_dump(),
        "params": params.model_dump(),
        "result": res.model_dump() if res else None,
        "numeric": numeric.model_dump(),
        "numeric_status": numeric.status,
        "suggested_diagnosis": suggested.model_dump(),
        "parent": {"cl": parent.cl, "cd": parent.cd, "fidelity": parent.fidelity} if parent else None,
    }
    checks = [
        {
            "name": c.name,
            "ok": c.ok,
            "value": c.value,
            "threshold": c.threshold,
            "severity": c.severity,
            "message": c.message,
        }
        for c in numeric.checks
    ]
    user = "\n\n".join(
        [
            _spec_block(spec),
            "## Candidate\n```json\n" + params.model_dump_json(indent=1) + "\n```",
            "## Solver result\n```json\n"
            + (res.model_dump_json(indent=1, exclude={"artifacts", "plots"}) if res else "null")
            + "\n```",
            "## Numeric validators (authoritative)\n"
            + markdown_table(checks, ("name", "ok", "value", "threshold", "severity", "message")),
            f"Numeric status: {numeric.status}",
            "## Parent design result\n" + (json.dumps(facts["parent"]) if parent else "(none)"),
            "## Suggested diagnosis (deterministic, from solver data)\n" + suggested.model_dump_json(indent=1),
        ]
    )
    return Brief(_system("critic", spec), user, facts)


def strategy_summary(s: StrategyMemo | None) -> str:
    if s is None:
        return ""
    focus = ", ".join(f"{f.name}{'' if f.direction == 'free' else ' ' + f.direction}" for f in s.focus_params)
    return f"{s.fidelity}/{s.mode} focus=[{focus}] r={s.trust_radius}"
