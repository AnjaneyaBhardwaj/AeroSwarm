"""Hybrid inner optimizer (BLUEPRINT §3 "Hybrid optimization"): Optuna TPE inside the Chief's subspace.

When the Chief's memo sets `mode="inner_optimizer"`, this loop spends up to `inner_budget` evaluations
at NeuralFoil, deterministically (no LLM call):

- search space: the memo's focus_params only, each within the trust region around the selected parent
  (`cad.apply.allowed_interval`), narrowed to one side by a "+"/"-" direction; every other parameter
  stays at the parent's value; the box lies on the parameter grid (so a quantized value never leaves it)
  and main_thickness starts at the rulebook's leading-edge-radius minimum;
- warm start: each NeuralFoil ledger record in the searched subspace (focus parameters in the search box,
  every other parameter equal to the parent's) is added to the study as a trial;
- objective: `baselines.tpe_value` (the constraint violation parent selection uses, objective as a
  tie-break), as in the Optuna baseline;
- each evaluation goes through the same path as the baselines (`baselines.record_evaluation`):
  geometry and rulebook checks, NeuralFoil, the numeric validator and the NeuralFoil screen. A proposal
  that fails the geometry checks, or repeats an evaluated design (`cad.apply.near_duplicate`), costs no
  evaluation and is told to TPE (INFEASIBLE_VALUE, or the earlier record's value);
- an exception while evaluating stops the run and keeps the records made so far (`inner_optimizer_error`);
- every evaluation is one ledger record (`EvalRecord.inner_optimizer=True`) and counts toward max_evals;
  the graph clips the budget so the last evaluation of the run stays free for a promotion.

It never promotes: the Chief sees the result in its next brief and decides promotions as usual.
Seeded from the parent cid and the generation, so a run is reproducible.
"""

from __future__ import annotations

import math
import time
import zlib
from dataclasses import dataclass, field

import numpy as np

from swarm.baselines import INFEASIBLE_VALUE, record_evaluation, tpe_value
from swarm.briefs import promotable
from swarm.cad.apply import allowed_interval, near_duplicate
from swarm.cad.build import build
from swarm.cad.regulations import RULEBOOKS, min_thickness_for_le_radius
from swarm.ledger import violation
from swarm.overrides import in_box
from swarm.solvers import neuralfoil
from swarm.state import PARAM_QUANTUM, DesignSpec, EvalRecord, StrategyMemo, WingParams, free_params, quantize

STARTUP_TRIALS = 3  # TPE's random start-up trials (warm-start trials count toward them)
MAX_WASTED_PROPOSALS = 60  # geometry-infeasible or repeated proposals per inner run before it stops
MIN_WIDTH = 2e-4  # a search interval narrower than this (two quanta) is dropped


def _on_grid(lo: float, hi: float) -> tuple[float, float]:
    """The interval shrunk onto the PARAM_QUANTUM grid, so every quantized value inside it is inside the
    Optuna distribution and inside the trust region (no float edge such as 1.2000000000000002)."""
    return quantize(math.ceil(lo / PARAM_QUANTUM - 1e-6) * PARAM_QUANTUM), quantize(
        math.floor(hi / PARAM_QUANTUM + 1e-6) * PARAM_QUANTUM
    )


def search_box(parent: WingParams, memo: StrategyMemo, spec: DesignSpec) -> dict[str, tuple[float, float]]:
    """Per focus parameter: the trust-region interval around the parent, one-sided for "+"/"-", on the
    parameter grid; main_thickness also starts at the rulebook's leading-edge-radius minimum."""
    box = {}
    for name in memo.focus_names:
        if name not in free_params(spec):
            continue
        lo, hi = allowed_interval(name, parent, memo.trust_radius)
        v = getattr(parent, name)
        d = memo.direction(name)
        if d == "+":
            lo = v
        elif d == "-":
            hi = v
        if name == "main_thickness" and spec.rulebook in RULEBOOKS:
            chord = spec.car.chord_mm * (1 - parent.flap_chord_ratio)
            lo = max(lo, min_thickness_for_le_radius(chord, spec.rulebook))
        lo, hi = _on_grid(lo, hi)
        if hi - lo >= MIN_WIDTH - 1e-12:
            box[name] = (lo, hi)
    return box


def in_region(p: WingParams, parent: WingParams, box: dict, spec: DesignSpec) -> bool:
    """The searched subspace: focus parameters inside the search box, every other parameter equal to the
    parent's (a warm-start trial only records the focus coordinates)."""
    for n, (lo, hi) in box.items():
        if not lo <= getattr(p, n) <= hi:
            return False
    other = {k: v for k, v in p.model_dump().items() if k not in box}
    ref = parent.model_dump()
    return all(abs(v - ref[k]) <= PARAM_QUANTUM / 2 for k, v in other.items())


def _clip(params: dict[str, float], box: dict) -> dict[str, float]:
    return {n: min(max(v, box[n][0]), box[n][1]) for n, v in params.items()}


def inner_seed(parent: WingParams, gen: int) -> int:
    return zlib.crc32(f"{parent.cid}:{gen}".encode())


@dataclass
class InnerRun:
    records: list[EvalRecord] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _brief_rec(rec: EvalRecord, spec: DesignSpec) -> dict:
    r = rec.result
    v = violation(rec, spec)
    return {
        "cid": rec.params.cid,
        "params": rec.params.model_dump(),
        "cl": r.cl,
        "cd": r.cd,
        "value": round(tpe_value(rec, spec), 6),
        "violation": {k: (round(x, 4) if np.isfinite(x) else None) for k, x in v.items()},
        "status": rec.verdict.status if rec.verdict else r.status,
        "screen_ok": None if rec.screen is None else rec.screen.ok,
        "in_target_box": in_box(r, spec),
    }


def run_inner(
    parent: WingParams,
    memo: StrategyMemo,
    spec: DesignSpec,
    ledger: list[EvalRecord],
    gen: int,
    run_dir: str,
    budget: int,
    deadline: float | None = None,
) -> InnerRun:
    """Run up to `budget` NeuralFoil evaluations of TPE proposals (see the module docstring)."""
    import optuna
    from optuna.distributions import FloatDistribution

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    out = InnerRun()
    box = search_box(parent, memo, spec)
    seed = inner_seed(parent, gen)
    base = {"node": "inner_optimize", "gen": gen}
    head = {
        "parent_cid": parent.cid,
        "focus": list(box),
        "box": {n: [round(a, 4), round(b, 4)] for n, (a, b) in box.items()},
        "trust_radius": memo.trust_radius,
        "budget": budget,
        "seed": seed,
    }
    if not box or budget <= 0:
        why = (
            "empty search box (no focus parameter with room to move)"
            if not box
            else "no evaluations left (the last one is kept for a promotion)"
        )
        out.summary = {**head, "evals": 0, "warm_trials": 0, "stopped": why, "best": None, "promotable": []}
        out.events.append(base | {"event": "inner_optimizer_finished"} | out.summary)
        return out

    names = list(box)
    dists = {n: FloatDistribution(*box[n]) for n in names}
    sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=STARTUP_TRIALS, multivariate=True)
    study = optuna.create_study(direction="minimize", sampler=sampler)

    # Warm start: NeuralFoil records in the searched subspace (one per cid, the latest).
    warm: dict[str, EvalRecord] = {}
    for r in ledger:
        if r.result.fidelity == "neuralfoil" and in_region(r.params, parent, box, spec):
            warm[r.params.cid] = r
    for r in warm.values():
        params = _clip({n: getattr(r.params, n) for n in names}, box)
        study.add_trial(optuna.trial.create_trial(params=params, distributions=dists, value=tpe_value(r, spec)))
    parent_nf = next(
        (r for r in reversed(ledger) if r.params.cid == parent.cid and r.result.fidelity == "neuralfoil"), None
    )
    head |= {
        "warm_trials": len(warm),
        "parent_value": None if parent_nf is None else round(tpe_value(parent_nf, spec), 6),
    }
    out.events.append(base | {"event": "inner_optimizer_started"} | head)

    seen = list(ledger)
    wasted = {"geometry": 0, "duplicate": 0}
    stopped = "budget"
    while len(out.records) < budget:
        if deadline is not None and time.time() >= deadline:
            stopped = "wall clock"
            break
        if wasted["geometry"] + wasted["duplicate"] >= MAX_WASTED_PROPOSALS:
            stopped = f"no new feasible design in the box after {MAX_WASTED_PROPOSALS} proposals"
            break
        trial = study.ask(dists)
        p = WingParams(**{**parent.model_dump(), **_clip({n: quantize(trial.params[n]) for n in names}, box)})
        dup = near_duplicate(p, seen, "neuralfoil")
        if dup is not None:
            study.tell(trial, tpe_value(dup, spec))
            wasted["duplicate"] += 1
            continue
        k = len(out.records) + 1
        try:
            geo = build(p, spec, run_dir)
            if geo.violations:
                study.tell(trial, INFEASIBLE_VALUE)
                wasted["geometry"] += 1
                continue
            res = neuralfoil.evaluate(p, spec)
            rec, _ = record_evaluation(
                gen,
                p,
                res,
                spec,
                seen,
                f"inner optimizer (TPE) evaluation {k}/{budget} around {parent.cid}",
                run_dir,
                geo.coords_path,
                parent_cid=parent.cid,
                inner_optimizer=True,
            )
        except Exception as e:  # keep what was evaluated so far: every evaluation stays a ledger record
            stopped = f"error: {e!r}"[:300]
            out.events.append(base | {"event": "inner_optimizer_error", "k": k, "cid": p.cid, "error": stopped})
            break
        study.tell(trial, tpe_value(rec, spec))
        out.records.append(rec)
        seen.append(rec)
        out.events.append(
            base
            | {"event": "inner_trial", "k": k, "cid": p.cid}
            | {n: getattr(p, n) for n in names}
            | {"cl": res.cl, "cd": res.cd, "status": rec.verdict.status, "value": round(tpe_value(rec, spec), 6)}
        )

    best = min(out.records, key=lambda r: tpe_value(r, spec)) if out.records else None
    new = {r.params.cid for r in out.records}
    promo = [r.params.cid for r in promotable(seen, spec) if r.params.cid in new]
    out.summary = {
        **head,
        "evals": len(out.records),
        "rejected_geometry": wasted["geometry"],
        "repeats": wasted["duplicate"],
        "stopped": stopped,
        "best": _brief_rec(best, spec) if best else None,
        "improved_on_parent": (
            None if best is None or head["parent_value"] is None else tpe_value(best, spec) < head["parent_value"]
        ),
        "in_target_box": [r.params.cid for r in out.records if in_box(r.result, spec)],
        "promotable": promo,
    }
    out.events.append(base | {"event": "inner_optimizer_finished"} | out.summary)
    return out
