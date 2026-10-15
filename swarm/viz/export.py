"""Run export for the static viewer (viewer/): one run directory -> one run.json.

Sources, and what each is trusted for:
- ledger.jsonl: every number (params, Cl, Cd, status, verdict, failing checks, stall margin).
- traces.jsonl: every piece of agent text (Chief hypothesis and focus, CAD changes and mechanisms,
  Critic diagnosis), verbatim from the model's structured output. Long text is cut at a word boundary
  and marked with an ellipsis; it is never rewritten.
- events.jsonl: which generation each trace belongs to, the parent choice, rejections and overrides.

Section outlines are computed here (race-car orientation, unit chord: `cad.build.placed`) so the page
never re-derives geometry. Nothing in the export is inferred from agent prose.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from swarm.cad.build import placed
from swarm.ledger import RunFiles, failing_checks, passing, violation
from swarm.state import DesignSpec, EvalRecord, WingParams, free_params

SCHEMA_VERSION = 1
OUTLINE_POINTS = 41  # per surface; 2n-1 points per outline
TRIM = {"hypothesis": 700, "mechanism": 500, "override": 400, "note": 500, "evidence": 300, "finding": 300}
ROLE_NODE = {"chief": "chief_plan", "cad": "cad_propose", "critic": "critic", "cfd": "cfd_solve"}
NOTABLE_EVENTS = {
    "geometry_rejected",
    "proposal_rejected",
    "screen_override",
    "screen_override_refused",
    "direct_xfoil_screened_out",
    "screen_xfoil_disagreement",
    "xfoil_recovery",
    "xfoil_ladder_exhausted",
    "escalate_to_xfoil",
    "inner_optimizer_finished",
    "cad_fallback",
    "cad_attempts_exhausted",
    "llm_error",
    "llm_error_reused_strategy",
    "llm_error_numeric_verdict",
    "cost_cap_reached",
    "llm_run_aborted",
}


def trim(text: str | None, limit: int) -> str:
    """Verbatim prefix of `text`, cut at a word boundary, with an ellipsis when cut."""
    if not text:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + " …"


def _num(x: float | None, nd: int = 6) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), nd)


def outline(params: WingParams, n: int = OUTLINE_POINTS) -> list[list[float]]:
    """Race-car-frame outline (inverted, rotated by alpha), unit chord, TE → suction → LE → pressure → TE."""
    xy = placed(params, n=n)
    return np.round(xy, 4).tolist()


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def assign_traces(traces: list[dict], events: list[dict]) -> list[tuple[int | None, dict]]:
    """(generation, trace) for each LLM trace. The graph appends a node's events right after the node
    returns, so a trace belongs to the first later event from the node of its role."""
    out = []
    for t in traces:
        if t.get("type") not in ("llm_call", "llm_failure"):
            continue
        ts = float(t["ts"])
        node = ROLE_NODE.get(t.get("role", ""))
        after = [e for e in events if float(e.get("ts", 0)) >= ts - 1e-3 and "gen" in e]
        match = next((e for e in after if e.get("node") == node), None) or (after[0] if after else None)
        out.append((None if match is None else int(match["gen"]), t))
    return out


def _stall(rec: EvalRecord) -> dict | None:
    """The stall-margin evidence for this record: the XFoil probe when it ran, else the NeuralFoil screen."""
    sm = rec.stall_margin
    if sm is not None:
        return {
            "source": "xfoil_probe",
            "dcl_dalpha": _num(sm.dcl_dalpha, 4),
            "threshold": sm.threshold,
            "ok": sm.ok,
            "failure": sm.failure,
        }
    sc = rec.screen
    if sc is not None:
        return {
            "source": "neuralfoil_screen",
            "dcl_dalpha": _num(sc.dcl_dalpha, 4),
            "threshold": sc.stall_threshold,
            "ok": sc.ok,
            "failure": None,
        }
    return None


def _eval(rec: EvalRecord, spec: DesignSpec) -> dict:
    r, v = rec.result, rec.verdict
    viol = violation(rec, spec)
    return {
        "cid": rec.params.cid,
        "parent_cid": rec.parent_cid,
        "params": {k: getattr(rec.params, k) for k in free_params(spec)},
        "solver": r.fidelity,
        "solver_level": r.solver_level,
        "fallback_from": r.fallback_from,
        "solver_status": r.status,
        "cl": _num(r.cl),
        "cd": _num(r.cd),
        "verdict": v.status if v else None,
        "symptom": v.diagnosis.symptom if v else None,
        "passing": passing(rec),
        "failing": failing_checks(rec, spec),
        "failed_checks": list(rec.failed_checks),
        "stall": _stall(rec),
        "violation": {k: _num(x, 5) for k, x in viol.items()},
        "inner_optimizer": rec.inner_optimizer,
        "quarantined": rec.quarantined,
        "rationale": trim(rec.rationale, TRIM["mechanism"]),
    }


def _headline(evals: list[dict]) -> int:
    """The generation's representative evaluation: a pass if any, else the smallest constraint violation
    (an inner-optimizer generation has several records), else the last."""
    if not evals:
        return -1
    for i, e in enumerate(evals):
        if e["passing"]:
            return i
    scored = [(sum(v for v in e["violation"].values() if v is not None), i) for i, e in enumerate(evals)]
    return min(scored)[1] if len(evals) > 1 else 0


def _chief(output: dict, effective: dict | None) -> dict:
    eff = effective or {}
    focus = output.get("focus_params") or []
    return {
        "hypothesis": trim(output.get("hypothesis"), TRIM["hypothesis"]),
        "focus": [
            {"name": f, "direction": "free", "locked": False}
            if isinstance(f, str)
            else {"name": f.get("name"), "direction": f.get("direction", "free"), "locked": bool(f.get("locked"))}
            for f in focus
        ],
        # what the graph executed (it may coerce the memo, e.g. inner optimizer disabled)
        "mode": eff.get("mode", output.get("mode")),
        "fidelity": eff.get("fidelity", output.get("fidelity")),
        "trust_radius": eff.get("trust_radius", output.get("trust_radius")),
        "promote_cid": eff.get("promote_cid", output.get("promote_cid")),
        "declare_plateau": bool(eff.get("declare_plateau", output.get("declare_plateau"))),
        "screen_override": trim(output.get("screen_override"), TRIM["override"]),
    }


def _cad(output: dict) -> dict:
    return {
        "changes": [
            {
                "name": c.get("name"),
                "new_value": c.get("new_value"),
                "mechanism": trim(c.get("mechanism"), TRIM["mechanism"]),
                "expected_dCl_sign": c.get("expected_dCl_sign"),
                "expected_dCd_sign": c.get("expected_dCd_sign"),
                "override_reason": trim(c.get("override_reason"), TRIM["override"]),
            }
            for c in output.get("changes") or []
        ],
        "note": trim(output.get("note"), TRIM["note"]),
    }


def _critic(output: dict) -> dict:
    diag = output.get("diagnosis") or {}
    return {
        "status": output.get("status"),
        "symptom": diag.get("symptom"),
        "x_over_c": diag.get("x_over_c"),
        "evidence": [trim(x, TRIM["evidence"]) for x in diag.get("evidence") or []],
        "findings": [
            {"observation": trim(f.get("observation"), TRIM["finding"]), "severity": f.get("severity")}
            for f in output.get("findings") or []
        ],
        "confidence": output.get("confidence"),
    }


def _event_note(e: dict) -> dict:
    """A short, factual line for a notable event (code-generated text, not agent prose)."""
    kind = e["event"]
    keep = {k: e[k] for k in ("cid", "reason", "violations", "error", "level", "action", "kind") if k in e}
    if kind == "inner_optimizer_finished":
        keep = {k: e.get(k) for k in ("evals", "stopped", "promotable", "in_target_box", "improved_on_parent")}
    if kind == "screen_xfoil_disagreement":
        keep = {k: v for k, v in e.items() if k not in ("ts", "node", "gen", "event")}
    if "error" in keep and isinstance(keep["error"], str):
        keep["error"] = trim(keep["error"], 300)
    if "reason" in keep and isinstance(keep["reason"], str):
        keep["reason"] = trim(keep["reason"], TRIM["override"])
    return {"event": kind, **keep}


def _summarise_outcome(ledger: list[EvalRecord], spec: DesignSpec, meta: dict) -> dict:
    from swarm.ledger import best_passing, closest_candidate

    best = best_passing(ledger, spec)
    if best is not None:
        first = next(i for i, r in enumerate(ledger) if passing(r))
        return {
            "result": "target_met" if meta.get("termination") == "target_met" else "passed",
            "cid": best.params.cid,
            "generation": best.generation,
            "evals_to_target": first + 1,
            "cl": _num(best.result.cl),
            "cd": _num(best.result.cd),
            "solver": best.result.fidelity,
            "failing": [],
        }
    close = closest_candidate(ledger, spec)
    return {
        "result": "no_pass",
        "cid": close.params.cid if close else None,
        "generation": close.generation if close else None,
        "evals_to_target": None,
        "cl": _num(close.result.cl) if close else None,
        "cd": _num(close.result.cd) if close else None,
        "solver": close.result.fidelity if close else None,
        "failing": failing_checks(close, spec) if close else [],
    }


def summarise_baseline(run_dir: str | Path) -> dict:
    """The comparison line for a baseline run (random / Optuna): outcome from its ledger and meta only."""
    files = RunFiles(run_dir)
    meta = json.loads(files.meta.read_text())
    spec = DesignSpec.model_validate(meta["spec"])
    ledger = files.read_ledger()
    return {
        "method": meta.get("method"),
        "label": meta.get("llm_client"),
        "seed": meta.get("start_seed"),
        "termination": meta.get("termination"),
        "evals": len(ledger),
        "xfoil_evals": sum(r.result.fidelity == "xfoil" for r in ledger),
        **_summarise_outcome(ledger, spec, meta),
    }


def export_run(run_dir: str | Path, name: str | None = None, baseline: dict | None = None) -> dict:
    """Build the viewer record for one run directory (see module docstring)."""
    run_dir = Path(run_dir)
    files = RunFiles(run_dir)
    meta = json.loads(files.meta.read_text())
    spec = DesignSpec.model_validate(meta["spec"])
    start = WingParams.model_validate(meta["start"])
    ledger = files.read_ledger()
    events = _read_jsonl(files.events)
    traces = _read_jsonl(files.traces)

    gens: dict[int, dict] = {}

    def gen(g: int) -> dict:
        return gens.setdefault(
            g,
            {
                "gen": g,
                "chief": None,
                "parent": None,
                "cad": [],
                "critic": None,
                "critic_source": None,
                "evals": [],
                "notes": [],
                "llm_failures": [],
            },
        )

    strategies = {e["gen"]: e["strategy"] for e in events if e.get("event") == "strategy"}
    for g, t in assign_traces(traces, events):
        if g is None:
            continue
        rec = gen(g)
        role = t.get("role")
        if t.get("type") == "llm_failure":
            rec["llm_failures"].append({"role": role, "error": trim(t.get("error"), 300)})
            continue
        out = t.get("output")
        if not isinstance(out, dict):
            continue
        if role == "chief":
            rec["chief"] = _chief(out, strategies.get(g))
        elif role == "cad":
            rec["cad"].append({**_cad(out), "outcome": None})
        elif role == "critic":
            rec["critic"], rec["critic_source"] = _critic(out), "llm"

    # CAD attempt outcomes, in order: accepted, rejected by validation, or rejected by geometry/rules.
    for g in sorted({e["gen"] for e in events if "gen" in e}):
        evs = [e for e in events if e.get("gen") == g]
        attempts = gen(g)["cad"]
        k = -1
        for e in evs:
            kind = e.get("event")
            if e.get("node") == "cad_propose" and kind in ("proposal_accepted", "proposal_rejected"):
                k += 1
                if k < len(attempts):
                    attempts[k]["outcome"] = "accepted" if kind == "proposal_accepted" else "rejected"
                    if kind == "proposal_rejected":
                        err = e.get("error") or {}
                        attempts[k]["rejection"] = trim(f"{err.get('kind')}: {err.get('msg')}", 400)
            elif kind == "geometry_rejected" and 0 <= k < len(attempts):
                attempts[k]["outcome"] = "rejected"
                attempts[k]["rejection"] = trim("; ".join(e.get("violations") or []), 400)
            elif kind == "chief_cad_disagreement" and 0 <= k < len(attempts):
                attempts[k].setdefault("disagreements", []).append(
                    {
                        "param": e.get("param"),
                        "chief": e.get("chief"),
                        "cad": e.get("cad"),
                        "reason": trim(e.get("reason"), TRIM["override"]),
                    }
                )
            elif kind == "parent_selected":
                gen(g)["parent"] = {"cid": e.get("cid"), "why": trim(e.get("why"), 300)}
            if kind in NOTABLE_EVENTS:
                gen(g)["notes"].append(_event_note(e))

    outlines: dict[str, list] = {start.cid: outline(start)}
    for r in ledger:
        rec = gen(r.generation)
        rec["evals"].append(_eval(r, spec))
        if r.params.cid not in outlines:
            outlines[r.params.cid] = outline(r.params)
        # A failed Critic call keeps the deterministic numeric verdict: say so rather than leave it blank.
        if rec["critic"] is None and r.verdict is not None and not r.inner_optimizer:
            rec["critic"] = _critic(r.verdict.model_dump())
            rec["critic_source"] = "numeric"

    generations = []
    for g in sorted(gens):
        rec = gens[g]
        rec["head"] = _headline(rec["evals"])
        generations.append(rec)

    usage = meta.get("llm_usage") or {}
    is_mock = bool(meta.get("is_mock"))
    return {
        "schema": SCHEMA_VERSION,
        "name": name or run_dir.name,
        "run_id": meta.get("run_id", run_dir.name),
        "preset": meta.get("preset"),
        "label": _label(meta),
        "is_mock": is_mock,
        "mock_notice": meta.get("mock_notice"),
        "llm_client": meta.get("llm_client"),
        "llm_valid": (meta.get("llm_health") or {}).get("valid"),
        "start_seed": meta.get("start_seed"),
        "inner_optimizer": meta.get("inner_optimizer"),
        "spec": {
            "component": spec.component,
            "target_cl": spec.target_cl,
            "cl_tol": spec.cl_tol,
            "cd_max": spec.cd_max,
            "reynolds": round(spec.reynolds),
            "speed_mps": spec.speed_mps,
            "max_evals": spec.max_evals,
            "rulebook": spec.rulebook,
        },
        "free_params": list(free_params(spec)),
        "bounds": {k: list(v) for k, v in WingParams.bounds().items() if k in free_params(spec)},
        "start": {k: getattr(start, k) for k in free_params(spec)},
        "start_cid": start.cid,
        "termination": meta.get("termination"),
        "evals": len(ledger),
        "cost_usd": _num(usage.get("cost_usd"), 4),
        "llm_calls": usage.get("calls"),
        "wall_hours": (meta.get("limits") or {}).get("wall_hours"),
        "outcome": _summarise_outcome(ledger, spec, meta),
        "baseline": baseline,
        "generations": generations,
        "outlines": outlines,
    }


def _label(meta: dict) -> str:
    if meta.get("method") in ("random", "optuna"):
        return f"{meta['method']} baseline (no LLM)"
    if meta.get("is_mock"):
        return "MockClient (rule-based stand-in, NOT an LLM)"
    return f"LLM swarm ({meta.get('llm_client')})"


def write_index(runs_dir: str | Path) -> dict:
    """viewer/runs/index.json: one entry per exported run, enough for the gallery and nearest-start search."""
    runs_dir = Path(runs_dir)
    entries = []
    for p in sorted(runs_dir.glob("*.json")):
        if p.name == "index.json":
            continue
        d = json.loads(p.read_text())
        if d.get("schema") != SCHEMA_VERSION:
            continue
        entries.append(
            {
                "file": p.name,
                "name": d["name"],
                "label": d["label"],
                "is_mock": d["is_mock"],
                "start": d["start"],
                "start_seed": d["start_seed"],
                "spec": d["spec"],
                "termination": d["termination"],
                "evals": d["evals"],
                "outcome": {k: d["outcome"][k] for k in ("result", "cl", "cd", "evals_to_target")},
            }
        )
    index = {"schema": SCHEMA_VERSION, "bounds": WingParams.bounds(), "runs": entries}
    (runs_dir / "index.json").write_text(json.dumps(index, indent=1))
    return index
