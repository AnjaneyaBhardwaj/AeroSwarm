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

Cost cap (`DesignSpec.max_cost_usd`): checked at every routing boundary. Once
the estimated LLM spend reaches the cap, no further LLM call is made: an
in-flight candidate is still solved and recorded with the deterministic
numeric verdict, then the run goes to `report` with termination "cost_cap".
The overshoot is therefore at most the one call that crossed the cap.

LLM validity (`LLMHealth` on the client's trace; real LLMs only): the run aborts at the
first routing boundary after more than `MAX_FAILED_CALLS` LLM calls have failed, with no
further LLM call, and ends with termination "invalid_llm". At the end of any real-LLM run
an agent that never got a successful call also makes it invalid. Every time a node
substitutes a deterministic output for an agent's, it is counted as that agent's fallback.
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
from swarm.briefs import near_target, screen_blocked
from swarm.cad.apply import apply_delta, fallback_params
from swarm.cad.build import build
from swarm.critic.numeric import VALIDATION, NumericReport, stall_check_required, suggest_diagnosis, validate
from swarm.critic.screen import compare_with_xfoil, surrogate_screen
from swarm.critic.stall import measure_stall_margin
from swarm.explore import current_parent, handle_plateau
from swarm.ledger import (
    RunFiles,
    best_passing,
    closest_candidate,
    failing_checks,
    latest_per_cid,
    objective,
    usable,
)
from swarm.llm.client import LLMClient
from swarm.overrides import override_allowed, track_record
from swarm.solvers import neuralfoil, xfoil
from swarm.state import (
    TERMINAL_FIDELITIES,
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
        "StallMargin",
        "SurrogateScreen",
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
    """The cid's highest-fidelity usable record (the one its verdict and diagnosis come from)."""
    return next((r for r in latest_per_cid(ledger) if r.params.cid == cid), None)


def _base(s: SwarmState, initial: WingParams) -> tuple[WingParams, str]:
    """The design the next CAD step modifies (`explore.current_parent`), and why."""
    rec, why = current_parent(s)
    return (rec.params, why) if rec else (initial, "baseline")


def build_graph(llm: LLMClient, files: RunFiles, initial: WingParams):
    run_dir = str(files.dir)

    def capped(s: SwarmState) -> bool:
        trace = getattr(llm, "trace", None)
        return trace is not None and trace.over_budget(s["spec"].max_cost_usd)

    def health():
        return getattr(getattr(llm, "trace", None), "health", None)

    def enforced() -> bool:
        return not llm.is_mock and health() is not None

    def aborted(s: SwarmState) -> bool:
        """Too many failed LLM calls: stop calling the LLM and end the run."""
        return enforced() and health().exceeded()

    def abort_event(node: str, s: SwarmState) -> dict:
        h = health()
        return {
            "node": node,
            "gen": s.get("generation", 0),
            "event": "llm_run_aborted",
            "failed_calls": h.failed_total,
            "limit": h.max_failed,
        }

    def fallback(role: str, kind: str, err: BaseException | None = None) -> None:
        trace = getattr(llm, "trace", None)
        if trace is not None:
            trace.log_fallback(role, kind, err)

    def cap_event(node: str, s: SwarmState) -> dict:
        t = llm.trace.totals
        return {
            "node": node,
            "gen": s.get("generation", 0),
            "event": "cost_cap_reached",
            "cost_usd": round(t["cost_usd"], 6),
            "cost_unknown_calls": t["cost_unknown_calls"],
            "cap_usd": s["spec"].max_cost_usd,
        }

    # ------------------------------------------------------------ chief
    @node_boundary("chief_plan", files)
    def chief_plan(s: SwarmState) -> dict:
        if aborted(s):
            return {"events": [abort_event("chief_plan", s)]}
        if capped(s):  # e.g. resumed after the cap was reached: plan nothing
            return {"events": [cap_event("chief_plan", s)]}
        spec, ledger = s["spec"], s.get("ledger", [])
        gen = s.get("generation", 0) + (1 if ledger else 0)
        st = {**s, "generation": gen}
        sbase, why = _base(st, initial)
        names = free_params(spec)
        sens = neuralfoil.sensitivities(sbase, spec, names)
        events: list[dict] = []
        try:
            memo, events = chief_agent.plan(llm, st, sens)
        except Exception as e:
            fallback("chief", "reused_strategy", e)
            prev = s.get("strategy")
            memo = prev or StrategyMemo(
                hypothesis="(chief unavailable) screen around best",
                focus_params=list(names[:3]),  # direction "free"
                trust_radius=0.15,
                fidelity="neuralfoil",
                mode="reasoned_step",
            )
            events.append(
                {"node": "chief_plan", "gen": gen, "event": "llm_error_reused_strategy", "error": repr(e)[:300]}
            )
        # A plateau before PLATEAU_MIN_FRACTION of the budget becomes exploration (widen or restart).
        memo, pev, branch = handle_plateau(memo, st, sbase if ledger else None)
        events += pev
        if branch is not None:
            sbase = next(r.params for r in ledger if r.params.cid == branch["anchor_cid"])
            why = f"plateau restart: {pev[0]['why']}"
            sens = neuralfoil.sensitivities(sbase, spec, names)
        events.append({"node": "chief_plan", "gen": gen, "event": "strategy", "strategy": memo.model_dump()})
        entry = {"gen": gen, "hypothesis": memo.hypothesis, "focus": [f.model_dump() for f in memo.focus_params]}
        entry |= {"fidelity": memo.fidelity, "promote_cid": memo.promote_cid, "screen_override": memo.screen_override}
        if pev:
            entry["explore"] = pev[0]["action"] + (f" from {pev[0]['anchor_cid']}" if branch else "")
        upd: dict[str, Any] = {
            "generation": gen,
            "strategy": memo,
            "events": events,
            "history": [entry],
            "retries": {**s.get("retries", {}), "cad": 0, "cad_gen": 0},
            "pending_violation": None,
            "delta": None,
        }
        if branch is not None:
            upd["exploration"] = branch
        if memo.promote_cid:
            rec = next(r for r in ledger if r.params.cid == memo.promote_cid)
            upd |= {"params": rec.params, "parent": rec.params}
        elif not ledger:
            upd |= {"params": initial, "parent": None}
        else:
            events.append({"node": "chief_plan", "gen": gen, "event": "parent_selected", "cid": sbase.cid, "why": why})
            upd |= {"params": None, "parent": sbase}
        upd["sens"] = sens
        return upd

    def route_after_chief(s: SwarmState) -> str:
        ledger, memo = s.get("ledger", []), s.get("strategy")
        if s.get("termination") == "fatal" or aborted(s) or _budget_spent(s) or capped(s):
            return "report"
        if memo and memo.declare_plateau and ledger:
            return "report"
        if s.get("params") is not None:  # baseline or promotion
            return "geometry_build"
        return "cad_propose"

    # ------------------------------------------------------------ cad
    @node_boundary("cad_propose", files)
    def cad_propose(s: SwarmState) -> dict:
        if aborted(s):
            return {"params": None, "events": [abort_event("cad_propose", s)]}
        if capped(s):
            return {"params": None, "events": [cap_event("cad_propose", s)]}
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
            fallback("cad", "deterministic_proposal")
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
        events = [{**ev, "event": "proposal_accepted", "cid": res.params.cid}]
        events += [
            {"node": "cad_propose", "gen": gen, "event": "chief_cad_disagreement", "cid": res.params.cid} | d
            for d in res.disagreements
        ]
        return {
            "params": res.params,
            "delta": delta,
            "pending_violation": None,
            "retries": retries,
            "events": events,
        }

    def route_after_cad(s: SwarmState) -> str:
        if s.get("termination") == "fatal" or aborted(s):
            return "report"
        if s.get("params") is not None and not s.get("pending_violation"):
            return "geometry_build"  # a proposal already paid for is still evaluated
        return "report" if capped(s) else "cad_propose"

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
        events = [{"node": "geometry_build", "gen": gen, "event": "geometry_ok", "cid": p.cid}]
        fidelity = memo.fidelity
        if fidelity != "neuralfoil" and memo.promote_cid != p.cid:
            # A fresh design sent straight past NeuralFoil is screened first. If it fails, a logged
            # screen_override sends it on, within the override rules (cap; NeuralFoil inside the box).
            sc = surrogate_screen(p, spec)
            if not sc.ok:
                ev = {"node": "geometry_build", "gen": gen, "cid": p.cid, "reasons": sc.reasons()}
                reason = memo.screen_override.strip()
                ok, why = override_allowed(s, neuralfoil.evaluate(p, spec)) if reason else (False, "")
                if ok:
                    events.append(ev | {"event": "screen_override", "fidelity": fidelity, "reason": reason})
                else:
                    if reason:
                        refused = {"event": "screen_override_refused", "kind": "direct to XFoil", "reason": reason}
                        events.append(ev | refused | {"why": why})
                    fidelity = "neuralfoil"
                    events.append(ev | {"event": "direct_xfoil_screened_out", "requested": memo.fidelity})
        return {
            "geometry": geo,
            "pending_violation": None,
            "solver": {"fidelity": fidelity, "level": 0, "tried": [], "fallback_from": None},
            "stall": None,
            "screen": None,
            "events": events,
        }

    def route_after_geometry(s: SwarmState) -> str:
        if s.get("termination") == "fatal" or aborted(s):
            return "report"
        if s.get("pending_violation"):
            return "report" if capped(s) else "cad_propose"
        return "cfd_solve"

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
        res, p, spec, ledger = s.get("result"), s["params"], s["spec"], s.get("ledger", [])
        gen = s.get("generation", 0)
        rep = validate(res, p, spec, ledger)
        stall, screen, events = None, None, []
        if res is not None and rep.ok:
            # NeuralFoil screen (one surrogate call): a check at NeuralFoil, a comparison at XFoil.
            screen = surrogate_screen(p, spec)
            if res.fidelity == "neuralfoil":
                rep = validate(res, p, spec, ledger, screen=screen)
        if stall_check_required(res, rep):
            # Only a candidate that clears every other check pays for the two extra solves.
            coords = s["geometry"].coords_path
            stall = measure_stall_margin(
                res, p.alpha_deg, lambda a, lvl: xfoil.evaluate(p, spec, coords, run_dir, lvl, alpha_deg=a)
            )
            rep = validate(res, p, spec, ledger, stall=stall)
            events.append(
                {"node": "numeric_validate", "gen": gen, "event": "stall_margin", "cid": p.cid} | stall.model_dump()
            )
        if screen is not None and res.fidelity != "neuralfoil":
            cmp = compare_with_xfoil(screen, res, stall)
            if cmp["disagree"]:
                events.append(
                    {"node": "numeric_validate", "gen": gen, "event": "screen_xfoil_disagreement", "cid": p.cid} | cmp
                )
        events.append(
            {
                "node": "numeric_validate",
                "gen": gen,
                "status": rep.status,
                "failed": [c.name for c in rep.checks if not c.ok],
            }
        )
        return {"numeric": rep, "stall": stall, "screen": screen, "events": events}

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
        rep: NumericReport = s["numeric"]
        if aborted(s):
            v = Verdict(
                status=rep.status,
                diagnosis=suggest_diagnosis(s.get("result"), spec, stall=s.get("stall"), screen=s.get("screen")),
                confidence=0.3,
            )
            events.append({**abort_event("critic", s), "action": "numeric verdict, no LLM call"})
        elif capped(s):
            v = Verdict(
                status=rep.status,
                diagnosis=suggest_diagnosis(s.get("result"), spec, stall=s.get("stall"), screen=s.get("screen")),
                confidence=0.3,
            )
            events.append({**cap_event("critic", s), "action": "numeric verdict, no LLM call"})
        else:
            try:
                v = critic_agent.review(llm, s, parent_rec)
            except Exception as e:
                fallback("critic", "numeric_verdict", e)
                v = Verdict(
                    status=rep.status,
                    diagnosis=suggest_diagnosis(s.get("result"), spec, stall=s.get("stall"), screen=s.get("screen")),
                    confidence=0.3,
                )
                events.append(
                    {"node": "critic", "gen": gen, "event": "llm_error_numeric_verdict", "error": repr(e)[:300]}
                )
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
            stall_margin=s.get("stall"),
            screen=s.get("screen"),
            failed_checks=[c.name for c in rep.checks if not c.ok and c.severity != "skipped"],
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
        return route_after_critic_fn(s, cost_capped=capped(s), aborted=aborted(s))

    # ------------------------------------------------------------ report
    @node_boundary("report", files)
    def report(s: SwarmState) -> dict:
        h = health()
        reasons = h.check(final=True) if enforced() else []
        term = termination_reason(s, cost_capped=capped(s), invalid=bool(reasons))
        write_report(s, files, term, llm)
        events = [cap_event("report", s)] if term == "cost_cap" else []
        return {"termination": term, "events": events + [{"node": "report", "event": "terminated", "reason": term}]}

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


def _evals_spent(s: SwarmState) -> bool:
    return len(s.get("ledger", [])) >= s["spec"].max_evals


def _wall_clock_spent(s: SwarmState) -> bool:
    t0 = s.get("started_at")
    return bool(t0) and (time.time() - t0) / 3600.0 >= s["spec"].max_wall_hours


def _budget_spent(s: SwarmState) -> bool:
    return _evals_spent(s) or _wall_clock_spent(s)


def target_met(s: SwarmState) -> bool:
    """PASS at a terminal fidelity, not a fallback, and inside the target box."""
    v, r, rep = s.get("verdict"), s.get("result"), s.get("numeric")
    return bool(v and r and rep and v.status == "PASS" and rep.terminal and not r.lower_fidelity)


def route_after_critic_fn(s: SwarmState, cost_capped: bool = False, aborted: bool = False) -> str:
    v = s["verdict"]
    if s.get("termination") == "fatal" or aborted or target_met(s) or _budget_spent(s) or cost_capped:
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


def termination_reason(s: SwarmState, cost_capped: bool = False, invalid: bool = False) -> str:
    """Which limit ended the run. eval_budget (max_evals), wall_clock (max_wall_hours) and
    cost_cap (max_cost_usd) are separate labels; "unknown" means no rule explains the stop."""
    if s.get("termination") == "fatal":
        return "fatal"
    if invalid:  # a real-LLM run that failed its validity rules is never target_met/eval_budget/...
        return "invalid_llm"
    if s.get("verdict") and target_met(s):
        return "target_met"
    if cost_capped:
        return "cost_cap"
    memo = s.get("strategy")
    if memo and memo.declare_plateau:
        return "plateau"
    if _evals_spent(s):
        return "eval_budget"
    if _wall_clock_spent(s):
        return "wall_clock"
    return "unknown"


TERMINATION_TEXT = {
    "target_met": "a design passed every check at XFoil",
    "eval_budget": "evaluation budget (max_evals) used up",
    "wall_clock": "wall-clock limit (max_wall_hours) reached",
    "cost_cap": "estimated LLM cost reached the cap (max_cost_usd)",
    "plateau": "the Chief declared a plateau",
    "fatal": "too many node errors",
    "invalid_llm": "the real-LLM run failed its validity rules",
    "unknown": "no termination rule matched (please report)",
}


def _record_section(rec: EvalRecord, spec: DesignSpec, viz: dict) -> list[str]:
    r = rec.result
    status = rec.verdict.status if rec.verdict else r.status
    lines = [
        f"`{rec.params.cid}` (gen {rec.generation}, {r.fidelity}"
        + (", lower-fidelity fallback" if r.lower_fidelity else "")
        + f"), status **{status}**",
        f"- Cl = {r.cl:.4f}, Cd = {r.cd:.5f}, objective = {objective(r, spec):.4f}",
    ]
    if rec.stall_margin is not None and rec.stall_margin.dcl_dalpha is not None:
        lines.append(
            f"- Stall margin d|Cl|/dα = {rec.stall_margin.dcl_dalpha:.3f}/deg (threshold {rec.stall_margin.threshold})"
        )
    plot = viz.get("stall_plots", {}).get(rec.params.cid)
    if plot:
        lines.append(f"- Stall-margin plot: [{Path(plot).name}]({Path(plot).name})")
    lines += [f"- Params: `{rec.params.model_dump_json()}`", ""]
    return lines


def _screen_cell(rec: EvalRecord) -> str:
    sc = rec.screen
    if sc is None:
        return ""
    if sc.ok:
        return "ok"
    return " + ".join(x for x, bad in (("stall", not sc.stall_ok), ("sep", sc.sep_warning)) if bad)


def write_report(s: SwarmState, files: RunFiles, term: str, llm: LLMClient) -> None:
    from swarm.viz.evolution import write_evolution

    spec, ledger = s["spec"], s.get("ledger", [])
    passed = best_passing(ledger, spec)
    closest = None if passed else closest_candidate(ledger, spec)
    viz = write_evolution(ledger, spec, files.dir) if any(usable(r) for r in ledger) else {}
    summary = (
        llm.trace.write_summary({"llm_client": llm.label, "is_mock": llm.is_mock}) if hasattr(llm, "trace") else {}
    )
    h = getattr(getattr(llm, "trace", None), "health", None)
    enforced = (not llm.is_mock) and h is not None
    health = h.snapshot(enforced) if h is not None else None
    t0 = s.get("started_at")
    limits = {
        "evals": len(ledger),
        "max_evals": spec.max_evals,
        "cost_usd": round(summary.get("cost_usd", 0.0), 6),
        "max_cost_usd": spec.max_cost_usd,
        "wall_hours": round((time.time() - t0) / 3600.0, 4) if t0 else None,
        "max_wall_hours": spec.max_wall_hours,
    }
    cap = f"cap ${spec.max_cost_usd:.2f}" if spec.max_cost_usd is not None else "no cost cap"
    wall = f"{limits['wall_hours']:.2f} h" if limits["wall_hours"] is not None else "n/a"
    lines = [f"# Run {files.dir.name}", ""]
    if health and enforced and not health["valid"]:
        lines += ["> **INVALID RUN: not usable as a real-LLM result.** `require_real_llm()` will refuse it."]
        lines += [f"> - {r}" for r in health["invalid_reasons"]] + [""]
    lines += [
        f"- LLM client: **{llm.label}**",
        f"- LLM health: **{'INVALID' if not health['valid'] else 'valid'}**"
        if health and enforced
        else "- LLM health: not enforced (mock)",
        f"- Termination: **{term}** ({TERMINATION_TEXT.get(term, term)})",
        f"- Limits: evaluations {len(ledger)} / {spec.max_evals}; est. LLM cost ${limits['cost_usd']:.4f} ({cap}); "
        f"wall clock {wall} / {spec.max_wall_hours} h",
        *_plateau_lines(s),
        f"- Target: Cl = {spec.target_cl} ± {spec.cl_tol}, Cd ≤ {spec.cd_max}, Re = {spec.reynolds:.3e}",
        f"- LLM calls: {summary.get('calls', 0)}, tokens in/out: {summary.get('input_tokens', 0)}/"
        f"{summary.get('output_tokens', 0)}",
        "",
    ]
    if health:
        lines += [
            "## LLM calls by agent",
            "",
            "| agent | ok | failed | fallbacks |",
            "|---|---|---|---|",
        ]
        a = health["agents"]
        lines += [f"| {k} | {v['ok']} | {v['failed']} | {v['fallbacks']} |" for k, v in a.items()]
        lines += [
            f"| **total** | {sum(v['ok'] for v in a.values())} | {health['failed_calls']} "
            f"| {sum(v['fallbacks'] for v in a.values())} |",
            "",
            f"failed = the call raised, was refused or returned nothing (a real-LLM run with more than "
            f"{health['max_failed_calls']} is aborted); fallbacks = a deterministic output replaced the agent's.",
            "",
        ]
    lines += ["## Best passing design", ""]
    if passed:
        lines += ["A full PASS: XFoil (not a fallback), in the target box, attached, with a stall margin.", ""]
        lines += _record_section(passed, spec, viz)
    else:
        lines += ["**None.** No design passed every check at a terminal fidelity (XFoil, not a fallback).", ""]
    if closest:
        lines += ["## Closest candidate (did not pass)", ""]
        lines += _record_section(closest, spec, viz)[:-1]
        lines += ["- **Failing check(s):**"] + [f"  - {w}" for w in failing_checks(closest, spec)] + [""]
    lines += [
        "## Ledger",
        "",
        "| gen | cid | fidelity | status | Cl | Cd | stall d\\|Cl\\|/dα | NF screen | quarantined |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for rec in ledger:
        r = rec.result
        cl = "" if r.cl is None else f"{r.cl:.4f}"
        cd = "" if r.cd is None else f"{r.cd:.5f}"
        sm = rec.stall_margin
        stall = "" if sm is None else ("n/a" if sm.dcl_dalpha is None else f"{sm.dcl_dalpha:.3f}")
        if rec.stall_untested:
            stall = "untested"
        lines.append(
            f"| {rec.generation} | {rec.params.cid} | {r.fidelity}{'*' if r.lower_fidelity else ''} "
            f"| {rec.verdict.status if rec.verdict else r.status} | {cl} | {cd} | {stall} | {_screen_cell(rec)} "
            f"| {rec.quarantined} |"
        )
    lines += [
        "",
        "`*` = lower-fidelity fallback. Only XFoil PASS rows are passing designs; a NeuralFoil PASS is a "
        "lower-tier result. NF screen = NeuralFoil stall (alpha+1/+2) and suction-side separation screen. "
        "stall untested = an XFoil result whose stall probe did not run (it runs only for a design that clears "
        "every other check); such a result is no evidence about the screen. "
        "All numbers above come from ledger.jsonl.",
        "",
    ]
    lines += _screen_section(ledger, spec)
    lines += _override_section(s)
    plots = viz.get("stall_plots", {})
    xf = [r for r in ledger if r.result.fidelity in TERMINAL_FIDELITIES and usable(r)]
    if xf:
        lines += ["## Stall-margin plots (XFoil candidates)", ""]
        for rec in xf:
            sm, plot = rec.stall_margin, plots.get(rec.params.cid)
            if sm is not None and plot:
                v = "probe failed" if sm.dcl_dalpha is None else f"d|Cl|/dα {sm.dcl_dalpha:.3f}/deg"
                ok = "ok" if sm.ok else f"< {sm.threshold}"
                lines.append(
                    f"- gen {rec.generation} `{rec.params.cid}`: {v} {ok} — [{Path(plot).name}]({Path(plot).name})"
                )
            else:
                why = "; ".join(failing_checks(rec, spec)) or "not in the target box"
                lines.append(
                    f"- gen {rec.generation} `{rec.params.cid}`: no probe "
                    f"(it runs only for in-box, attached results: {why})"
                )
        lines.append("")
    if viz:
        lines += [f"![evolution]({Path(viz['strip']).name})", ""]
    (files.dir / "report.md").write_text("\n".join(lines))
    files.write_meta(
        {
            "termination": term,
            "evals": len(ledger),
            "limits": limits,
            "llm_usage": summary,
            "llm_health": health,
            "viz": viz,
            "best_passing_cid": passed.params.cid if passed else None,
            "closest_candidate_cid": closest.params.cid if closest else None,
            "closest_candidate_failing": failing_checks(closest, spec) if closest else [],
        }
    )


def _plateau_lines(s: SwarmState) -> list[str]:
    """Plateau declarations that did not end the run (before PLATEAU_MIN_FRACTION of max_evals)."""
    ev = [e for e in s.get("events", []) if e.get("event") == "plateau_deferred"]
    if not ev:
        return []
    items = []
    for e in ev:
        what = e["action"]
        if what in ("widen", "restart"):
            what += f" (trust radius {e['trust_radius'][0]} → {e['trust_radius'][1]})"
        if e["action"] == "restart":
            what += f" from `{e['anchor_cid']}`"
        items.append(f"gen {e['gen']} {what}")
    return [f"- Plateau declarations deferred (allowed after {ev[0]['allowed_after']} evals): " + "; ".join(items)]


def _override_section(s: SwarmState) -> list[str]:
    """Each screen override used or refused, and what XFoil found (`overrides.track_record`)."""
    rec = track_record(s)
    if not rec:
        return []
    lines = ["## Screen overrides", ""]
    lines += [f"- gen {r['gen']} {r['kind']} of `{r['cid']}`: {r['outcome']}" for r in rec]
    return lines + [""]


def _screen_section(ledger: list[EvalRecord], spec: DesignSpec) -> list[str]:
    """NeuralFoil screen: promotions it blocked and how it compares with XFoil on the same geometry."""
    blocked = sorted((r for r in near_target(ledger, spec) if screen_blocked(r)), key=lambda r: r.generation)
    xf = [r for r in ledger if r.screen is not None and r.result.fidelity in TERMINAL_FIDELITIES]
    compared = [r for r in xf if not r.stall_untested]
    untested = [r for r in xf if r.stall_untested]
    if not blocked and not xf:
        return []
    lines = ["## NeuralFoil screen", ""]
    if blocked:
        lines += ["Blocked from promotion to XFoil (near the target at NeuralFoil, screen failed):", ""]
        lines += [f"- gen {r.generation} `{r.params.cid}`: {'; '.join(r.screen.reasons())}" for r in blocked] + [""]
    if compared:
        lines += [
            "Screen vs XFoil on the same geometry (XFoil is authoritative):",
            "",
            "| gen | cid | screen d\\|Cl\\|/dα | XFoil d\\|Cl\\|/dα | screen TE H | XFoil TE sep x/c | disagree |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in compared:
            cmp = compare_with_xfoil(r.screen, r.result, r.stall_margin)
            sc, sm = r.screen, r.stall_margin
            xs = "" if sm is None or sm.dcl_dalpha is None else f"{sm.dcl_dalpha:.3f}"
            ns = "" if sc.dcl_dalpha is None else f"{sc.dcl_dalpha:.3f}"
            sep = r.result.bl.te_separation_xc if r.result.bl is not None else None
            h = f"{sc.te_shape_factor[0]:.2f}" if sc.te_shape_factor else ""
            lines.append(
                f"| {r.generation} | {r.params.cid} | {ns} | {xs} | {h} | {'' if sep is None else f'{sep:.2f}'} "
                f"| {', '.join(cmp['disagree']) or '-'} |"
            )
        lines += [
            "",
            f"Stall: XFoil needs d|Cl|/dα ≥ {VALIDATION.stall_min_dcl_dalpha} (when its probe ran); the screen "
            f"needs d|Cl|/dα ≥ {VALIDATION.screen_min_dcl_dalpha} and suction-side TE H < "
            f"{VALIDATION.screen_h_probe_max} at alpha+1/+2. Separation: the screen warns at suction-side TE H ≥ "
            f"{VALIDATION.screen_h_sep} at alpha.",
            "",
        ]
    if untested:
        lines += [
            f"Not evidence about the screen ({len(untested)} XFoil result(s) with the stall probe not run, "
            "stall_untested): " + ", ".join(f"gen {r.generation} `{r.params.cid}`" for r in untested),
            "",
        ]
    return lines
