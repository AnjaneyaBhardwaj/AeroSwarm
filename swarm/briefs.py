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
from swarm.ledger import best_record, markdown_table, no_improve_streak, objective, row, usable
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


def _system(role: str, spec: DesignSpec) -> str:
    tpl = (PROMPTS / f"{role}.md").read_text()
    return tpl.format(
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
    cols = ("gen", "cid", "fidelity", "status", "cl", "cd", "objective")
    promo = [r.params.cid for r in promotable(ledger, spec)]
    blocked = {r.params.cid: r.screen.reasons() for r in near_target(ledger, spec) if screen_blocked(r)}
    streak = no_improve_streak(ledger, spec)
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
    }
    user = "\n\n".join(
        [
            _spec_block(spec),
            f"Generation {facts['generation']}; evaluations used {len(ledger)} of {spec.max_evals}. "
            f"Free parameters: {', '.join(facts['free_params'])}.",
            "## Best 5 (lowest objective = |Cl−target| + 20·max(0, Cd−cd_max))\n" + markdown_table(best5, cols),
            "## Last 5\n" + markdown_table(last5, cols),
            "## Failure table\n" + markdown_table(fails[-10:], cols),
            "## Best design parameters\n" + (json.dumps(facts["best"]["params"]) if best else "(none yet)"),
            "## Sensitivities at the best design (NeuralFoil; per unit parameter; race-car Cl)\n"
            + json.dumps(sens, indent=1),
            "## Critic's latest verdict\n" + (v.model_dump_json(indent=1) if v else "(none)"),
            f"## Promotion candidates (within {NEAR_TARGET_FACTOR}·tol at neuralfoil, not yet run at xfoil)\n"
            + (", ".join(promo) or "(none)"),
            "## Blocked from promotion by the NeuralFoil screen (alpha+1/+2 slope, suction-side TE H)\n"
            + ("\n".join(f"- {cid}: {'; '.join(why)}" for cid, why in blocked.items()) or "(none)"),
            f"Generations without improvement: {streak}.",
        ]
    )
    return Brief(_system("chief", spec), user, facts)


def cad_brief(state: SwarmState, base: WingParams, base_rec: EvalRecord | None, sens: dict) -> Brief:
    spec, strat = state["spec"], state["strategy"]
    assert strat is not None
    v = state.get("verdict")
    diag = v.diagnosis if v else None
    allowed = [p for p in strat.focus_params if p in free_params(spec)]
    bounds = WingParams.bounds()
    intervals = {p: allowed_interval(p, base, strat.trust_radius) for p in allowed}
    heur = [h.model_dump() for h in lookup_heuristics(diag.symptom, allowed)] if diag else []
    res = base_rec.result if base_rec else None
    facts = {
        "spec": spec.model_dump(),
        "generation": state.get("generation", 0),
        "base": base.model_dump(),
        "base_result": {"cl": res.cl, "cd": res.cd, "fidelity": res.fidelity} if res else None,
        "focus_params": allowed,
        "trust_radius": strat.trust_radius,
        "bounds": {p: bounds[p] for p in allowed},
        "intervals": intervals,
        "sensitivities": {p: sens[p] for p in allowed if p in sens},
        "diagnosis": diag.model_dump() if diag else None,
        "heuristics": heur,
        "pending_violation": state.get("pending_violation"),
        "cad_retries": state.get("retries", {}).get("cad", 0),
    }
    user = "\n\n".join(
        [
            _spec_block(spec),
            "## Current design (WingParams)\n```json\n" + base.model_dump_json(indent=1) + "\n```",
            "## Its result\n" + (json.dumps(facts["base_result"]) if res else "(not evaluated yet)"),
            f"## Allowed changes (trust radius {strat.trust_radius} of range)\n"
            + "\n".join(
                f"- {p}: bounds {bounds[p]}, allowed interval [{a:.4f}, {b:.4f}]" for p, (a, b) in intervals.items()
            ),
            "## Sensitivities (per unit change; race-car Cl, negative = more downforce)\n"
            + json.dumps(facts["sensitivities"], indent=1),
            "## Critic diagnosis\n" + (diag.model_dump_json(indent=1) if diag else "(none)"),
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
    return "" if s is None else f"{s.fidelity}/{s.mode} focus={s.focus_params} r={s.trust_radius}"
