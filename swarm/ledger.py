"""Ledger helpers: objective, best-so-far, compressed views, and run files.

Numbers in reports come only from here (the ledger), never from agent text.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from swarm.state import FIDELITY_RANK, TERMINAL_FIDELITIES, CFDResult, DesignSpec, EvalRecord

CD_PENALTY = 20.0  # 0.001 of Cd over budget costs as much as 0.02 of Cl error


def objective(result: CFDResult, spec: DesignSpec) -> float:
    if result.cl is None or result.cd is None or not math.isfinite(result.cl) or not math.isfinite(result.cd):
        return float("inf")
    return abs(result.cl - spec.target_cl) + CD_PENALTY * max(0.0, result.cd - spec.cd_max)


def usable(rec: EvalRecord) -> bool:
    """Eligible for best-so-far: physical, numerically sound, with coefficients."""
    if rec.quarantined or rec.result.cl is None or rec.result.cd is None:
        return False
    if not (math.isfinite(rec.result.cl) and math.isfinite(rec.result.cd)):
        return False
    return rec.verdict is None or rec.verdict.status in ("PASS", "TARGET_MISS")


def best_record(ledger: list[EvalRecord], spec: DesignSpec, fidelity: str | None = None) -> EvalRecord | None:
    rows = [r for r in ledger if usable(r) and (fidelity is None or r.result.fidelity == fidelity)]
    if not rows:
        return None
    return min(rows, key=lambda r: (objective(r.result, spec), -FIDELITY_RANK[r.result.fidelity]))


def passing(rec: EvalRecord) -> bool:
    """A full PASS: the run could end on it (PASS verdict at a terminal fidelity, not a fallback).

    The numeric validator only gives PASS at XFoil with a passing stall margin and no TE
    separation, and the Critic can downgrade but never upgrade, so this is `target_met`.
    """
    return (
        usable(rec)
        and rec.verdict is not None
        and rec.verdict.status == "PASS"
        and rec.result.fidelity in TERMINAL_FIDELITIES
        and not rec.result.lower_fidelity
    )


def best_passing(ledger: list[EvalRecord], spec: DesignSpec) -> EvalRecord | None:
    rows = [r for r in ledger if passing(r)]
    return min(rows, key=lambda r: objective(r.result, spec)) if rows else None


def closest_candidate(ledger: list[EvalRecord], spec: DesignSpec) -> EvalRecord | None:
    """The best objective among designs that did not pass; terminal-fidelity results first,
    because a NeuralFoil-only design has not been checked where it counts."""
    rows = [r for r in ledger if usable(r) and not passing(r)]
    if not rows:
        return None
    return min(rows, key=lambda r: (r.result.fidelity not in TERMINAL_FIDELITIES, objective(r.result, spec)))


def failing_checks(rec: EvalRecord, spec: DesignSpec) -> list[str]:
    """Why `rec` is not a full PASS, one line per reason, from ledger facts only."""
    if passing(rec):
        return []
    r, out = rec.result, []
    named = set(rec.failed_checks)
    if r.cl is not None and r.cd is not None:
        if abs(r.cl - spec.target_cl) > spec.cl_tol:
            off = abs(r.cl - spec.target_cl)
            out.append(f"target box: Cl {r.cl:.4f} is {off:.4f} from {spec.target_cl} (tol {spec.cl_tol})")
        if r.cd > spec.cd_max:
            out.append(f"target box: Cd {r.cd:.5f} > cd_max {spec.cd_max}")
    sep = r.bl.te_separation_xc if r.bl is not None else None
    if sep is not None:
        out.append(f"te_separation: suction-side Cf < 0 from x/c {sep:.2f} to the TE")
    sm = rec.stall_margin
    if sm is not None and not sm.ok:
        if sm.dcl_dalpha is None:
            out.append(f"stall_margin: probe failed ({sm.failure})")
        else:
            seps = [f"x/c {x:.2f} at {a:g}°" for a, x in zip(sm.alphas_deg, sm.te_separation_xc, strict=False) if x]
            out.append(
                f"stall_margin: d|Cl|/dα {sm.dcl_dalpha:.3f}/deg < {sm.threshold}"
                + (f" (TE separation {', '.join(seps)})" if seps else "")
            )
    elif "stall_margin" in named and sm is None:
        out.append("stall_margin: probe not run")
    if "neuralfoil_screen" in named and rec.screen is not None:
        out += rec.screen.reasons()
    known = {"te_separation", "stall_margin", "neuralfoil_screen"}
    out += [f"{n}: failed" for n in rec.failed_checks if n not in known]
    if r.fidelity not in TERMINAL_FIDELITIES:
        out.append(f"fidelity: {r.fidelity} only; only a terminal fidelity (XFoil) can pass")
    elif r.lower_fidelity:
        out.append(f"fidelity: fallback result (requested {r.fallback_from})")
    if not out and rec.verdict is not None and rec.verdict.status != "PASS":
        out.append(f"verdict: {rec.verdict.status} ({rec.verdict.diagnosis.symptom})")
    return out


def no_improve_streak(ledger: list[EvalRecord], spec: DesignSpec) -> int:
    """Generations since the best objective last improved."""
    best, streak, last_gen = float("inf"), 0, None
    for r in ledger:
        if r.generation == last_gen:
            continue
        j = objective(r.result, spec) if usable(r) else float("inf")
        if j < best - 1e-6:
            best, streak = j, 0
        else:
            streak += 1
        last_gen = r.generation
    return streak


def row(r: EvalRecord, spec: DesignSpec) -> dict:
    res = r.result
    return {
        "gen": r.generation,
        "cid": r.params.cid,
        "fidelity": res.fidelity,
        "status": r.verdict.status if r.verdict else res.status,
        "cl": None if res.cl is None else round(res.cl, 4),
        "cd": None if res.cd is None else round(res.cd, 5),
        "objective": None if not usable(r) else round(objective(res, spec), 4),
        "quarantined": r.quarantined,
        "lower_fidelity": res.lower_fidelity,
        "params": {k: v for k, v in r.params.model_dump().items()},
    }


def markdown_table(rows: list[dict], cols: tuple[str, ...]) -> str:
    if not rows:
        return "(none)"
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows)


class RunFiles:
    """runs/<id>/: ledger.jsonl, events.jsonl, traces.jsonl, meta.json, per-cid artifacts."""

    def __init__(self, run_dir: str | Path):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ledger = self.dir / "ledger.jsonl"
        self.events = self.dir / "events.jsonl"
        self.traces = self.dir / "traces.jsonl"
        self.meta = self.dir / "meta.json"

    def append_record(self, rec: EvalRecord) -> None:
        with self.ledger.open("a") as f:
            f.write(rec.model_dump_json() + "\n")

    def append_events(self, events: list[dict]) -> None:
        if not events:
            return
        with self.events.open("a") as f:
            for e in events:
                f.write(json.dumps({"ts": time.time(), **e}, default=str) + "\n")

    def write_meta(self, meta: dict) -> None:
        cur = json.loads(self.meta.read_text()) if self.meta.exists() else {}
        cur.update(meta)
        self.meta.write_text(json.dumps(cur, indent=2, default=str))

    def read_ledger(self) -> list[EvalRecord]:
        if not self.ledger.exists():
            return []
        return [EvalRecord.model_validate_json(line) for line in self.ledger.read_text().splitlines() if line]
