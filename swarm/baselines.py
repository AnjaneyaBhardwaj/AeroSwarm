"""Benchmark baselines: seeded random feasible starts, and random search through the pipeline's gates.

Random search uses exactly the agents' evaluation path, minus the agents: the same geometry build
(FS2026 checks), NeuralFoil + numeric validator + NeuralFoil screen, the same promotion rule
(`briefs.promotable`: within 2*tol at NeuralFoil, under the Cd cap, screen passed), and the same XFoil
ladder, stall-margin probe and validator. Each step promotes the best promotable design if there is
one, else evaluates a uniform random sample of the free parameters over their bounds. Every
NeuralFoil or XFoil evaluation is one ledger record (one unit of the evaluation budget), as in a run.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import numpy as np

from swarm.briefs import promotable
from swarm.cad.build import build
from swarm.critic.numeric import stall_check_required, suggest_diagnosis, validate
from swarm.critic.screen import surrogate_screen
from swarm.critic.stall import measure_stall_margin
from swarm.ledger import RunFiles
from swarm.solvers import neuralfoil, xfoil
from swarm.state import CFDResult, DesignSpec, EvalRecord, Verdict, WingParams, free_params, quantize

RANDOM_SEARCH_LABEL = "random search (uniform over the free-parameter bounds; same screen and XFoil gate)"


def _sample(rng: np.random.Generator, spec: DesignSpec, base: WingParams) -> WingParams:
    bounds = WingParams.bounds()
    upd = {n: quantize(rng.uniform(*bounds[n])) for n in free_params(spec)}
    return WingParams(**{**base.model_dump(), **upd})


def random_start(
    seed: int, spec: DesignSpec, template: WingParams | None = None, max_tries: int = 10_000
) -> WingParams:
    """A seeded, uniformly sampled feasible start: passes the geometry/FS2026 checks and gives a
    physical NeuralFoil result with downforce (Cl < 0). Not necessarily near the target."""
    rng = np.random.default_rng(seed)
    base = template or WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=4.0)
    with tempfile.TemporaryDirectory() as tmp:
        for _ in range(max_tries):
            p = _sample(rng, spec, base)
            if build(p, spec, tmp).violations:
                continue
            r = neuralfoil.evaluate(p, spec)
            rep = validate(r, p, spec, [])
            if rep.ok and r.cl is not None and r.cl < 0:
                return p
    raise RuntimeError(f"no feasible start found for seed {seed}")


def _xfoil(p: WingParams, spec: DesignSpec, coords: str, run_dir: str) -> CFDResult:
    r = None
    for lvl in range(xfoil.MAX_LEVEL + 1):  # the ladder, as cfd_recover walks it
        r = xfoil.evaluate(p, spec, coords, run_dir, lvl)
        if r.status == "converged":
            break
    return r


def _record(gen, p, res, spec, ledger, rationale, run_dir, coords=None) -> tuple[EvalRecord, object]:
    rep = validate(res, p, spec, ledger)
    stall = screen = None
    if res.cl is not None and rep.ok:
        screen = surrogate_screen(p, spec)
        if res.fidelity == "neuralfoil":
            rep = validate(res, p, spec, ledger, screen=screen)
    if stall_check_required(res, rep):
        stall = measure_stall_margin(
            res, p.alpha_deg, lambda a, lvl: xfoil.evaluate(p, spec, coords, run_dir, lvl, alpha_deg=a)
        )
        rep = validate(res, p, spec, ledger, stall=stall)
    diag = suggest_diagnosis(res, spec, stall=stall, screen=screen)
    return EvalRecord(
        generation=gen,
        params=p,
        result=res,
        verdict=Verdict(status=rep.status, diagnosis=diag, confidence=1.0),
        rationale=rationale,
        quarantined=rep.status == "NON_PHYSICAL",
        stall_margin=stall,
        screen=screen,
        failed_checks=[c.name for c in rep.checks if not c.ok and c.severity != "skipped"],
    ), rep


class _NoLLM:
    label, kind, is_mock = RANDOM_SEARCH_LABEL, "random", True


def random_search(
    spec: DesignSpec, start: WingParams, seed: int, run_dir: str | Path, write_report: bool = True
) -> dict:
    """Run random search under `spec`'s evaluation and wall-clock limits; returns the meta dict."""
    from swarm.graph import write_report as _write_report

    files = RunFiles(run_dir)
    rng = np.random.default_rng(seed + 1_000_003)  # independent of the start sampler
    t0 = time.time()
    ledger: list[EvalRecord] = []
    term = "eval_budget"
    p = start
    gen = 0
    while len(ledger) < spec.max_evals:
        if (time.time() - t0) / 3600.0 >= spec.max_wall_hours:
            term = "wall_clock"
            break
        promo = promotable(ledger, spec) if ledger else []
        if promo:
            p = promo[0].params
            geo = build(p, spec, files.dir)
            res, why = _xfoil(p, spec, geo.coords_path, str(files.dir)), f"promotion of {p.cid} to xfoil"
        else:
            if ledger:
                p = _sample(rng, spec, start)
                while build(p, spec, files.dir).violations:  # infeasible geometry costs no evaluation
                    p = _sample(rng, spec, start)
            geo = build(p, spec, files.dir)
            res, why = neuralfoil.evaluate(p, spec), "baseline" if not ledger else "random sample"
        rec, rep = _record(gen, p, res, spec, ledger, why, str(files.dir), geo.coords_path)
        ledger.append(rec)
        files.append_record(rec)
        gen += 1
        if rep.terminal and rep.status == "PASS":
            term = "target_met"
            break
    meta = {
        "method": "random",
        "llm_client": RANDOM_SEARCH_LABEL,
        "is_mock": True,
        "spec": spec.model_dump(),
        "start": start.model_dump(),
        "start_seed": seed,
    }
    files.write_meta(meta)
    if write_report:
        _write_report({"spec": spec, "ledger": ledger, "started_at": t0}, files, term, _NoLLM())
    else:
        files.write_meta({"termination": term, "evals": len(ledger)})
    return {**meta, "termination": term, "evals": len(ledger), "wall_hours": (time.time() - t0) / 3600.0}
