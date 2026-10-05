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
            if sm.dcl_dalpha < sm.threshold:
                out.append(
                    f"stall_margin: d|Cl|/dα {sm.dcl_dalpha:.3f}/deg < {sm.threshold}"
                    + (f" (TE separation {', '.join(seps)})" if seps else "")
                )
            else:
                out.append(f"stall_margin: TE separation within the probe range ({', '.join(seps)})")
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


def latest_per_cid(ledger: list[EvalRecord]) -> list[EvalRecord]:
    """One record per usable cid: its highest-fidelity result (XFoil overrides NeuralFoil), latest first."""
    out: dict[str, EvalRecord] = {}
    for r in ledger:
        if not usable(r):
            continue
        cur = out.get(r.params.cid)
        if cur is None or FIDELITY_RANK[r.result.fidelity] >= FIDELITY_RANK[cur.result.fidelity]:
            out[r.params.cid] = r
    return list(out.values())


def violation(rec: EvalRecord, spec: DesignSpec) -> dict[str, float]:
    """Constraint violation, each term in units of its own threshold (0 = satisfied).

    stall: shortfall of d|Cl|/dalpha below the threshold (XFoil probe if it ran, else the
    NeuralFoil screen; a probe that could not be solved counts as 1). separation: 1 if the
    design separates at its alpha or within the probe range (XFoil facts, else the screen's
    warning). box: distance outside the target box, Cl in units of cl_tol plus Cd excess at
    the objective's exchange rate (CD_PENALTY), also in units of cl_tol.
    """
    r, sm, sc = rec.result, rec.stall_margin, rec.screen
    stall = 0.0
    if sm is not None:
        stall = 1.0 if sm.dcl_dalpha is None else max(0.0, sm.threshold - sm.dcl_dalpha) / sm.threshold
    elif sc is not None:
        stall = 1.0 if sc.dcl_dalpha is None else max(0.0, sc.stall_threshold - sc.dcl_dalpha) / sc.stall_threshold
    sep = r.bl is not None and r.bl.te_separation_xc is not None
    if sm is not None:
        sep = sep or any(x is not None for x in sm.te_separation_xc[1:])
    elif sc is not None and r.fidelity == "neuralfoil":
        sep = sep or sc.sep_warning
    box = float("inf")
    if r.cl is not None and r.cd is not None and math.isfinite(r.cl) and math.isfinite(r.cd):
        out = max(0.0, abs(r.cl - spec.target_cl) - spec.cl_tol) + CD_PENALTY * max(0.0, r.cd - spec.cd_max)
        box = out / spec.cl_tol
    return {"stall": stall, "separation": float(sep), "box": box, "total": stall + float(sep) + box}


def passed_at_fidelity(rec: EvalRecord) -> bool:
    """PASS verdict at the record's own fidelity (a NeuralFoil PASS includes the screen)."""
    return usable(rec) and rec.verdict is not None and rec.verdict.status == "PASS"


def select_parent(ledger: list[EvalRecord], spec: DesignSpec) -> tuple[EvalRecord | None, str]:
    """The design the next CAD step modifies, and why.

    The best design that passed all checks at its fidelity (judged on each cid's highest-fidelity
    record, so an XFoil rejection overrides a NeuralFoil pass). If none passed, the design with
    the smallest constraint violation (`violation`), objective as the tie-break; never the
    objective alone, which happily picks an in-box design with no stall margin.
    """
    rows = latest_per_cid(ledger)
    if not rows:
        return None, "no usable design yet"
    ok = [r for r in rows if passed_at_fidelity(r)]
    if ok:
        best = min(ok, key=lambda r: (objective(r.result, spec), -FIDELITY_RANK[r.result.fidelity]))
        return best, f"passed all checks at {best.result.fidelity}"
    best = min(rows, key=lambda r: (violation(r, spec)["total"], objective(r.result, spec)))
    v = violation(best, spec)
    why = ", ".join(f"{k} {v[k]:.2f}" for k in ("stall", "separation", "box"))
    return best, f"nothing passed; least constraint violation ({why})"


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


def _stall_probe(r: EvalRecord) -> str:
    """XFoil stall-margin probe: ok / fail / untested (did not run); empty below XFoil."""
    if r.stall_untested:
        return "untested"
    sm = r.stall_margin
    return "" if sm is None else ("ok" if sm.ok else "fail")


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
        "failing": (failing_checks(r, spec) or [""])[0][:90],
        "stall_probe": _stall_probe(r),
        "params": {k: v for k, v in r.params.model_dump().items()},
    }


MOVE_TOL = 1e-6


def dial_coverage(ledger: list[EvalRecord], names: list[str]) -> list[dict]:
    """Per parameter: the range explored over all evaluated designs, the moves (designs whose value
    differs from their parent's, up/down), and the last move. Says nothing about which way is good."""
    from swarm.state import WingParams

    bounds = WingParams.bounds()
    first: dict[str, EvalRecord] = {}
    for r in ledger:
        first.setdefault(r.params.cid, r)
    out = []
    for n in names:
        lo, hi = bounds[n]
        vals = [getattr(r.params, n) for r in first.values()]
        moves = []
        for r in first.values():
            par = first.get(r.parent_cid) if r.parent_cid and r.parent_cid != r.params.cid else None
            if par is not None and abs(getattr(r.params, n) - getattr(par.params, n)) > MOVE_TOL:
                moves.append((r.generation, getattr(par.params, n), getattr(r.params, n)))
        last = moves[-1] if moves else None
        out.append(
            {
                "param": n,
                "bounds": [lo, hi],
                "explored": [min(vals), max(vals)] if vals else None,
                "share_of_range": round((max(vals) - min(vals)) / (hi - lo), 3) if vals else 0.0,
                "moves": len(moves),
                "up": sum(b > a for _, a, b in moves),
                "down": sum(b < a for _, a, b in moves),
                "last_move": {"gen": last[0], "from": last[1], "to": last[2]} if last else None,
            }
        )
    return out


def dial_coverage_table(cov: list[dict]) -> str:
    rows = [
        {
            "param": c["param"],
            "bounds": f"{c['bounds'][0]:g}–{c['bounds'][1]:g}",
            "explored": f"{c['explored'][0]:.4g}–{c['explored'][1]:.4g}" if c["explored"] else "",
            "share of range": f"{100 * c['share_of_range']:.0f}%",
            "moves (up/down)": f"{c['moves']} ({c['up']}/{c['down']})",
            "last move": (
                f"gen {c['last_move']['gen']}: {c['last_move']['from']:.4g} → {c['last_move']['to']:.4g}"
                if c["last_move"]
                else "never moved"
            ),
        }
        for c in cov
    ]
    return markdown_table(rows, ("param", "bounds", "explored", "share of range", "moves (up/down)", "last move"))


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
