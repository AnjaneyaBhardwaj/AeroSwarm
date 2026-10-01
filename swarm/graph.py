"""The agent graph (BLUEPRINT §1 topology, §3 routing).

START → chief_plan ─┬─► cad_propose ⇄ (tool errors / geometry violations, ≤3 tries, then fallback)
                    ├─► geometry_build (baseline or promotion: no CAD step)
                    └─► report
cad_propose → geometry_build → cfd_solve → numeric_validate ─┬─► critic
                                   ▲                         └─► cfd_recover (numerical failure)
                                   └──────── cfd_recover ◄───┘
critic → route_after_critic → report | cad_propose | chief_plan

LLM nodes: chief_plan, cad_propose, critic. In milestone 1 cfd_recover is
deterministic (next untried XFoil ladder level, then NeuralFoil fallback).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from swarm.agents import cad as cad_agent
from swarm.agents import chief as chief_agent
from swarm.agents import critic as critic_agent
from swarm.cad.apply import apply_delta, fallback_params
from swarm.cad.build import build
from swarm.critic.numeric import NumericReport, suggest_diagnosis, validate
from swarm.ledger import RunFiles, best_record, objective, usable
from swarm.llm.client import LLMClient
from swarm.solvers import neuralfoil, xfoil
from swarm.state import (
    CFDResult,
    DesignSpec,
    EvalRecord,
    StrategyMemo,
    SwarmState,
    Verdict,
    WingParams,
    free_params,
)

MAX_CAD_RETRIES = 3
MAX_CAD_ATTEMPTS_PER_GEN = 12
MAX_NODE_ERRORS = 5

# Types the checkpointer may deserialize (explicit allowlist; nothing else is revived).
CHECKPOINT_TYPES = [
    ("swarm.state", n)
    for n in (
        "DesignSpec",
        "ReferenceCar",
        "WingParams",
        "StrategyMemo",
        "GeometryArtifact",
        "CFDResult",
        "BoundaryLayerSummary",
        "Verdict",
        "Diagnosis",
        "Finding",
        "EvalRecord",
        "ParamDelta",
        "ParamChange",
    )
] + [("swarm.critic.numeric", "NumericReport"), ("swarm.critic.numeric", "Check")]


@contextmanager
def checkpointer(path: str | Path) -> Iterator[SqliteSaver]:
    """SqliteSaver at runs/<id>/ckpt.db so a crashed run resumes at the failed node."""
    with closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        yield SqliteSaver(conn, serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES))


def node_boundary(name: str, files: RunFiles, on_error: dict | None = None):
    """Every node degrades instead of crashing the graph; events go to events.jsonl."""

    def deco(fn):
        def wrapped(state: SwarmState) -> dict:
            try:
                upd = fn(state) or {}
            except Exception as e:  # tool/infra failure, not LLM output
                errors = state.get("retries", {}).get("errors", 0) + 1
                upd = {
                    "events": [{"node": name, "error": repr(e)[:500], "gen": state.get("generation", 0)}],
                    "pending_violation": f"{name} failed: {e!s}"[:500],
                    "retries": {**state.get("retries", {}), "errors": errors},
                    **(on_error or {}),
                }
                if errors >= MAX_NODE_ERRORS:
                    upd["termination"] = "fatal"
            files.append_events(upd.get("events", []))
            return upd

        wrapped.__name__ = name
        return wrapped

    return deco


def _record_for(ledger: list[EvalRecord], cid: str) -> EvalRecord | None:
    rows = [r for r in ledger if r.params.cid == cid and usable(r)]
    return rows[-1] if rows else None


def _base(ledger: list[EvalRecord], spec: DesignSpec, initial: WingParams, fidelity: str | None = None):
    rec = (best_record(ledger, spec, fidelity) if fidelity else None) or best_record(ledger, spec)
    return (rec.params, rec) if rec else (initial, None)


def build_graph(llm: LLMClient, files: RunFiles, initial: WingParams):
    run_dir = str(files.dir)

    # ------------------------------------------------------------ chief
    @node_boundary("chief_plan", files)
    def chief_plan(s: SwarmState) -> dict:
        spec, ledger = s["spec"], s.get("ledger", [])
        gen = s.get("generation", 0) + (1 if ledger else 0)
        sbase, _ = _base(ledger, spec, initial)
        names = free_params(spec)
        sens = neuralfoil.sensitivities(sbase, spec, names)
        st = {**s, "generation": gen}
        events: list[dict] = []
        try:
            memo, events = chief_agent.plan(llm, st, sens)
        except Exception as e:
            prev = s.get("strategy")
            memo = prev or StrategyMemo(
                hypothesis="(chief unavailable) screen around best",
                focus_params=list(names[:3]),
                trust_radius=0.15,
                fidelity="neuralfoil",
                mode="reasoned_step",
            )
            events.append(
                {"node": "chief_plan", "gen": gen, "event": "llm_error_reused_strategy", "error": repr(e)[:300]}
            )
        events.append({"node": "chief_plan", "gen": gen, "event": "strategy", "strategy": memo.model_dump()})
        upd: dict[str, Any] = {
            "generation": gen,
            "strategy": memo,
            "events": events,
            "retries": {**s.get("retries", {}), "cad": 0, "cad_gen": 0},
            "pending_violation": None,
            "delta": None,
        }
        if memo.promote_cid:
            rec = next(r for r in ledger if r.params.cid == memo.promote_cid)
            upd |= {"params": rec.params, "parent": rec.params}
        elif not ledger:
            upd |= {"params": initial, "parent": None}
        else:
            parent, prec = _base(ledger, spec, initial, memo.fidelity)
            if parent.cid != sbase.cid:
                sens = neuralfoil.sensitivities(parent, spec, names)
            upd |= {"params": None, "parent": parent}
        upd["sens"] = sens
        return upd

    def route_after_chief(s: SwarmState) -> str:
        ledger, memo = s.get("ledger", []), s.get("strategy")
        if s.get("termination") == "fatal" or _budget_spent(s):
            return "report"
        if memo and memo.declare_plateau and ledger:
            return "report"
        if s.get("params") is not None:  # baseline or promotion
            return "geometry_build"
        return "cad_propose"

    # ------------------------------------------------------------ cad
    @node_boundary("cad_propose", files)
    def cad_propose(s: SwarmState) -> dict:
        spec, ledger, memo = s["spec"], s.get("ledger", []), s["strategy"]
        retries = dict(s.get("retries", {}))
        gen = s.get("generation", 0)
        base = s.get("parent") or initial
        base_rec = _record_for(ledger, base.cid)
        retries["cad_gen"] = retries.get("cad_gen", 0) + 1
        if retries["cad_gen"] > MAX_CAD_ATTEMPTS_PER_GEN:
            return {
                "termination": "fatal",
                "retries": retries,
                "events": [{"node": "cad_propose", "gen": gen, "event": "cad_attempts_exhausted"}],
            }
        if retries.get("cad", 0) >= MAX_CAD_RETRIES:
            p = fallback_params(base, memo, spec, ledger, seed=gen * 100 + retries["cad_gen"])
            retries["cad"] = 0
            return {
                "params": p,
                "delta": None,
                "pending_violation": None,
                "retries": retries,
                "events": [
                    {"node": "cad_propose", "gen": gen, "event": "cad_fallback", "cid": p.cid, "params": p.model_dump()}
                ],
            }
        try:
            delta = cad_agent.propose(llm, s, base, base_rec, s.get("sens", {}))
        except Exception as e:
            retries["cad"] = retries.get("cad", 0) + 1
            return {
                "params": None,
                "pending_violation": f"llm_error: {e!s}"[:300],
                "retries": retries,
                "events": [{"node": "cad_propose", "gen": gen, "event": "llm_error", "error": repr(e)[:300]}],
            }
        res = apply_delta(base, delta, memo, spec, ledger)
        ev = {"node": "cad_propose", "gen": gen, "delta": delta.model_dump()}
        if not res.ok:
            retries["cad"] = retries.get("cad", 0) + 1
            msg = res.error.render()
            return {
                "params": None,
                "delta": delta,
                "pending_violation": msg,
                "retries": retries,
                "events": [{**ev, "event": "proposal_rejected", "error": res.error.model_dump()}],
            }
        return {
            "params": res.params,
            "delta": delta,
            "pending_violation": None,
            "retries": retries,
            "events": [{**ev, "event": "proposal_accepted", "cid": res.params.cid}],
        }

    def route_after_cad(s: SwarmState) -> str:
        if s.get("termination") == "fatal":
            return "report"
        return "geometry_build" if s.get("params") is not None and not s.get("pending_violation") else "cad_propose"

    # ------------------------------------------------------------ geometry
    @node_boundary("geometry_build", files)
    def geometry_build(s: SwarmState) -> dict:
        p, spec, memo = s["params"], s["spec"], s["strategy"]
        geo = build(p, spec, run_dir)
        gen = s.get("generation", 0)
        if geo.violations:
            retries = dict(s.get("retries", {}))
            retries["cad"] = retries.get("cad", 0) + 1
            return {
                "geometry": geo,
                "pending_violation": "; ".join(geo.violations),
                "retries": retries,
                "parent": s.get("parent") or p,
                "events": [
                    {
                        "node": "geometry_build",
                        "gen": gen,
                        "event": "geometry_rejected",
                        "cid": p.cid,
                        "violations": geo.violations,
                    }
                ],
            }
        return {
            "geometry": geo,
            "pending_violation": None,
            "solver": {"fidelity": memo.fidelity, "level": 0, "tried": [], "fallback_from": None},
            "events": [{"node": "geometry_build", "gen": gen, "event": "geometry_ok", "cid": p.cid}],
        }

    def route_after_geometry(s: SwarmState) -> str:
        if s.get("termination") == "fatal":
            return "report"
        return "cad_propose" if s.get("pending_violation") else "cfd_solve"

    # ------------------------------------------------------------ cfd
    @node_boundary("cfd_solve", files, on_error={"result": None})
    def cfd_solve(s: SwarmState) -> dict:
        p, spec, solver = s["params"], s["spec"], s["solver"]
        if solver["fidelity"] == "xfoil":
            r = xfoil.evaluate(p, spec, s["geometry"].coords_path, run_dir, solver["level"])
        else:
            r = neuralfoil.evaluate(p, spec, fallback_from=solver.get("fallback_from"))
        return {
            "result": r,
            "events": [
                {
                    "node": "cfd_solve",
                    "gen": s.get("generation", 0),
                    "cid": p.cid,
                    "fidelity": r.fidelity,
                    "level": r.solver_level,
                    "status": r.status,
                    "signature": r.failure_signature,
                    "fallback_from": r.fallback_from,
                    "cl": r.cl,
                    "cd": r.cd,
                    "wall_s": round(r.wall_s, 4),
                }
            ],
        }

    @node_boundary("numeric_validate", files)
    def numeric_validate(s: SwarmState) -> dict:
        rep = validate(s.get("result"), s["params"], s["spec"], s.get("ledger", []))
        return {
            "numeric": rep,
            "events": [
                {
                    "node": "numeric_validate",
                    "gen": s.get("generation", 0),
                    "status": rep.status,
                    "failed": [c.name for c in rep.checks if not c.ok],
                }
            ],
        }

    def recoverable(s: SwarmState) -> bool:
        rep: NumericReport | None = s.get("numeric")
        r = s.get("result")
        if rep is None or rep.failure_class != "NUMERICAL_FAILURE":
            return False
        return r is None or r.fallback_from is None

    def route_after_numeric(s: SwarmState) -> str:
        return "cfd_recover" if recoverable(s) else "critic"

    @node_boundary("cfd_recover", files)
    def cfd_recover(s: SwarmState) -> dict:
        r, solver = s.get("result"), dict(s["solver"])
        gen = s.get("generation", 0)
        if solver["fidelity"] == "neuralfoil":
            new = {"fidelity": "xfoil", "level": 0, "tried": [], "fallback_from": None}
            ev = {"event": "escalate_to_xfoil", "reason": "surrogate confidence / failure"}
        else:
            tried = solver["tried"] + [solver["level"]]
            nxt = xfoil.next_level(tried)
            if nxt is not None:
                new = {**solver, "level": nxt, "tried": tried}
                ev = {
                    "event": "xfoil_recovery",
                    "from_level": solver["level"],
                    "to_level": nxt,
                    "action": xfoil.LEVEL_NAMES[nxt],
                }
            else:
                new = {"fidelity": "neuralfoil", "level": 0, "tried": tried, "fallback_from": "xfoil"}
                ev = {"event": "xfoil_ladder_exhausted", "action": "neuralfoil fallback (lower fidelity)"}
        return {
            "solver": new,
            "events": [{"node": "cfd_recover", "gen": gen, "signature": r.failure_signature if r else None, **ev}],
        }

    # ------------------------------------------------------------ critic
    @node_boundary("critic", files)
    def critic(s: SwarmState) -> dict:
        spec, ledger, p = s["spec"], s.get("ledger", []), s["params"]
        parent = s.get("parent")
        parent_rec = _record_for(ledger, parent.cid) if parent else None
        gen = s.get("generation", 0)
        events = []
        try:
            v = critic_agent.review(llm, s, parent_rec)
        except Exception as e:
            rep: NumericReport = s["numeric"]
            v = Verdict(status=rep.status, diagnosis=suggest_diagnosis(s.get("result"), spec), confidence=0.3)
            events.append({"node": "critic", "gen": gen, "event": "llm_error_numeric_verdict", "error": repr(e)[:300]})
        delta = s.get("delta")
        memo = s["strategy"]
        if delta is not None:
            rationale = "; ".join(f"{c.name}→{c.new_value}: {c.mechanism}" for c in delta.changes)
            signs = {c.name: (c.expected_dCl_sign, c.expected_dCd_sign) for c in delta.changes}
        elif memo and memo.promote_cid == p.cid:
            rationale, signs = f"promotion of {p.cid} to {memo.fidelity}", {}
        elif not ledger:
            rationale, signs = "baseline", {}
        else:
            rationale, signs = "deterministic fallback (CAD retries exhausted)", {}
        res = s.get("result") or CFDResult(
            cid=p.cid,
            fidelity=s.get("solver", {}).get("fidelity", "neuralfoil"),
            status="not_converged",
            failure_signature="no_result",
        )
        rec = EvalRecord(
            generation=gen,
            params=p,
            result=res,
            verdict=v,
            rationale=rationale,
            quarantined=v.status == "NON_PHYSICAL",
            predicted_signs=signs,
            parent_cid=parent.cid if parent else None,
        )
        files.append_record(rec)
        events.append(
            {
                "node": "critic",
                "gen": gen,
                "event": "verdict",
                "cid": p.cid,
                "status": v.status,
                "symptom": v.diagnosis.symptom,
                "quarantined": rec.quarantined,
            }
        )
        retries = {**s.get("retries", {}), "cad": 0}
        return {"verdict": v, "ledger": [rec], "events": events, "retries": retries}

    def route_after_critic(s: SwarmState) -> str:
        return route_after_critic_fn(s)

    # ------------------------------------------------------------ report
    @node_boundary("report", files)
    def report(s: SwarmState) -> dict:
        term = termination_reason(s)
        write_report(s, files, term, llm)
        return {"termination": term, "events": [{"node": "report", "event": "terminated", "reason": term}]}

    g = StateGraph(SwarmState)
    for name, fn in [
        ("chief_plan", chief_plan),
        ("cad_propose", cad_propose),
        ("geometry_build", geometry_build),
        ("cfd_solve", cfd_solve),
        ("numeric_validate", numeric_validate),
        ("cfd_recover", cfd_recover),
        ("critic", critic),
        ("report", report),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "chief_plan")
    g.add_conditional_edges("chief_plan", route_after_chief, ["report", "geometry_build", "cad_propose"])
    g.add_conditional_edges("cad_propose", route_after_cad, ["geometry_build", "cad_propose", "report"])
    g.add_conditional_edges("geometry_build", route_after_geometry, ["cad_propose", "cfd_solve", "report"])
    g.add_edge("cfd_solve", "numeric_validate")
    g.add_conditional_edges("numeric_validate", route_after_numeric, ["cfd_recover", "critic"])
    g.add_edge("cfd_recover", "cfd_solve")
    g.add_conditional_edges("critic", route_after_critic, ["report", "cad_propose", "cfd_recover", "chief_plan"])
    g.add_edge("report", END)
    return g


def _budget_spent(s: SwarmState) -> bool:
    spec = s["spec"]
    if len(s.get("ledger", [])) >= spec.max_evals:
        return True
    t0 = s.get("started_at")
    return bool(t0) and (time.time() - t0) / 3600.0 >= spec.max_wall_hours


def target_met(s: SwarmState) -> bool:
    """PASS at a terminal fidelity, not a fallback, and inside the target box."""
    v, r, rep = s.get("verdict"), s.get("result"), s.get("numeric")
    return bool(v and r and rep and v.status == "PASS" and rep.terminal and not r.lower_fidelity)


def route_after_critic_fn(s: SwarmState) -> str:
    v = s["verdict"]
    if s.get("termination") == "fatal" or target_met(s) or _budget_spent(s):
        return "report"
    # NUMERICAL_FAILURE reaches the critic only after the ladder (and fallback) is
    # exhausted: escalate to the Chief with the failure record (Scenario B step 4).
    return {
        "NON_PHYSICAL": "cad_propose",
        "NUMERICAL_FAILURE": "chief_plan",
        "UNSTEADY": "cad_propose",
        "TARGET_MISS": "chief_plan",
        "PASS": "chief_plan",
    }[v.status]


def termination_reason(s: SwarmState) -> str:
    if s.get("termination") == "fatal":
        return "fatal"
    if s.get("verdict") and target_met(s):
        return "target_met"
    memo = s.get("strategy")
    if memo and memo.declare_plateau:
        return "plateau"
    return "budget"


def write_report(s: SwarmState, files: RunFiles, term: str, llm: LLMClient) -> None:
    from swarm.viz.evolution import write_evolution

    spec, ledger = s["spec"], s.get("ledger", [])
    best = best_record(ledger, spec)
    best_x = best_record(ledger, spec, "xfoil")
    viz = write_evolution(ledger, spec, files.dir) if any(usable(r) for r in ledger) else {}
    summary = (
        llm.trace.write_summary({"llm_client": llm.label, "is_mock": llm.is_mock}) if hasattr(llm, "trace") else {}
    )
    lines = [
        f"# Run {files.dir.name}",
        "",
        f"- LLM client: **{llm.label}**",
        f"- Termination: **{term}**",
        f"- Evaluations: {len(ledger)} / {spec.max_evals}",
        f"- Target: Cl = {spec.target_cl} ± {spec.cl_tol}, Cd ≤ {spec.cd_max}, Re = {spec.reynolds:.3e}",
        f"- LLM calls: {summary.get('calls', 0)}, tokens in/out: {summary.get('input_tokens', 0)}/"
        f"{summary.get('output_tokens', 0)}, est. cost ${summary.get('cost_usd', 0.0):.4f}",
        "",
    ]
    for label, rec in (("Best overall", best), ("Best at XFoil", best_x)):
        if rec:
            r = rec.result
            lines += [
                f"## {label}: `{rec.params.cid}` (gen {rec.generation}, {r.fidelity}"
                + (", lower-fidelity fallback" if r.lower_fidelity else "")
                + ")",
                f"- Cl = {r.cl:.4f}, Cd = {r.cd:.5f}, objective = {objective(r, spec):.4f}",
                f"- Params: `{rec.params.model_dump_json()}`",
                "",
            ]
    lines += [
        "## Ledger",
        "",
        "| gen | cid | fidelity | status | Cl | Cd | quarantined |",
        "|---|---|---|---|---|---|---|",
    ]
    for rec in ledger:
        r = rec.result
        cl = "" if r.cl is None else f"{r.cl:.4f}"
        cd = "" if r.cd is None else f"{r.cd:.5f}"
        lines.append(
            f"| {rec.generation} | {rec.params.cid} | {r.fidelity}{'*' if r.lower_fidelity else ''} "
            f"| {rec.verdict.status if rec.verdict else r.status} | {cl} | {cd} | {rec.quarantined} |"
        )
    lines += ["", "`*` = lower-fidelity fallback. All numbers above come from ledger.jsonl.", ""]
    if viz:
        lines += [f"![evolution]({Path(viz['strip']).name})", ""]
    (files.dir / "report.md").write_text("\n".join(lines))
    files.write_meta(
        {
            "termination": term,
            "evals": len(ledger),
            "llm_usage": summary,
            "viz": viz,
            "best_cid": best.params.cid if best else None,
            "best_xfoil_cid": best_x.params.cid if best_x else None,
        }
    )
