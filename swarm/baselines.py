"""Benchmark baselines: seeded random feasible starts, and random search through the pipeline's gates.

Random search uses exactly the agents' evaluation path, minus the agents: the same geometry build
(rulebook checks), NeuralFoil + numeric validator + NeuralFoil screen, the same promotion rule
(`briefs.promotable`: within 2*tol at NeuralFoil, under the Cd cap, screen passed), and the same XFoil
ladder, stall-margin probe and validator. Each step promotes the best promotable design if there is
one, else evaluates a uniform random sample of the free parameters over their bounds. Every
NeuralFoil or XFoil evaluation is one ledger record (one unit of the evaluation budget), as in a run.

Optuna TPE runs the same loop with the uniform sampler replaced by a seeded TPE sampler (Optuna
defaults otherwise). It minimizes the same constraint violation the agents' parent selection uses
(`ledger.violation`: stall shortfall + separation + distance outside the target box, objective as a
tie-break). The start is its first trial; an XFoil result of a promoted design is added as a trial
at the same point, so TPE learns from the authoritative tier. A proposal that fails the geometry
checks costs no evaluation and is told to TPE as INFEASIBLE_VALUE.
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
from swarm.ledger import RunFiles, objective, violation
from swarm.solvers import neuralfoil, xfoil
from swarm.state import CFDResult, DesignSpec, EvalRecord, Verdict, WingParams, free_params, quantize

RANDOM_SEARCH_LABEL = "random search (uniform over the free-parameter bounds; same screen and XFoil gate)"
TPE_LABEL = "Optuna TPE (seeded; minimizes constraint violation; same screen and XFoil gate)"
INFEASIBLE_VALUE = 1000.0  # TPE value for a geometry-infeasible or unsolved proposal
MAX_GEOMETRY_TRIES = 10_000


def _sample(rng: np.random.Generator, spec: DesignSpec, base: WingParams) -> WingParams:
    bounds = WingParams.bounds()
    upd = {n: quantize(rng.uniform(*bounds[n])) for n in free_params(spec)}
    return WingParams(**{**base.model_dump(), **upd})


def random_start(
    seed: int, spec: DesignSpec, template: WingParams | None = None, max_tries: int = 10_000
) -> WingParams:
    """A seeded, uniformly sampled feasible start: passes the geometry and rulebook checks and gives a
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
    def __init__(self, label: str, kind: str):
        self.label, self.kind, self.is_mock = label, kind, True


def tpe_value(rec: EvalRecord, spec: DesignSpec) -> float:
    """What TPE minimizes: the constraint violation, objective as a small tie-break."""
    v = violation(rec, spec)["total"]
    if not np.isfinite(v):
        return INFEASIBLE_VALUE
    return float(v + 1e-3 * min(objective(rec.result, spec), 10.0))


class _Uniform:
    """Random search's proposer: a uniform sample of the free parameters."""

    def __init__(self, spec: DesignSpec, start: WingParams, seed: int):
        self.spec, self.start = spec, start
        self.rng = np.random.default_rng(seed + 1_000_003)  # independent of the start sampler

    def ask(self) -> WingParams:
        return _sample(self.rng, self.spec, self.start)

    def reject(self, p: WingParams) -> None:
        pass

    def tell(self, p: WingParams, rec: EvalRecord) -> None:
        pass


class _TPE:
    """Optuna TPE proposer over the free parameters' bounds (ask/tell)."""

    def __init__(self, spec: DesignSpec, start: WingParams, seed: int):
        import optuna
        from optuna.distributions import FloatDistribution

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.optuna, self.spec, self.start = optuna, spec, start
        bounds = WingParams.bounds()
        self.names = list(free_params(spec))
        self.dists = {n: FloatDistribution(*bounds[n]) for n in self.names}
        self.sampler = optuna.samplers.TPESampler(seed=seed + 1_000_003)
        self.study = optuna.create_study(direction="minimize", sampler=self.sampler)
        self.pending = None

    def ask(self) -> WingParams:
        self.pending = self.study.ask(self.dists)
        upd = {n: quantize(self.pending.params[n]) for n in self.names}
        return WingParams(**{**self.start.model_dump(), **upd})

    def reject(self, p: WingParams) -> None:
        self.study.tell(self.pending, INFEASIBLE_VALUE)
        self.pending = None

    def tell(self, p: WingParams, rec: EvalRecord) -> None:
        value = tpe_value(rec, self.spec)
        if self.pending is not None:
            self.study.tell(self.pending, value)
            self.pending = None
        else:  # the start, or an XFoil result of a promoted design: a trial at that point
            params = {n: getattr(p, n) for n in self.names}
            self.study.add_trial(self.optuna.trial.create_trial(params=params, distributions=self.dists, value=value))


METHODS = {"random": (_Uniform, RANDOM_SEARCH_LABEL, "random sample"), "optuna": (_TPE, TPE_LABEL, "tpe sample")}


def search(
    method: str, spec: DesignSpec, start: WingParams, seed: int, run_dir: str | Path, write_report: bool = True
) -> dict:
    """Run a baseline under `spec`'s evaluation and wall-clock limits; returns the meta dict.

    Each step promotes the best promotable design to XFoil if there is one, else evaluates the
    proposer's next geometry-feasible sample at NeuralFoil (the start first)."""
    from swarm.graph import write_report as _write_report

    cls, label, why_sample = METHODS[method]
    proposer = cls(spec, start, seed)
    files = RunFiles(run_dir)
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
                for _ in range(MAX_GEOMETRY_TRIES):
                    p = proposer.ask()
                    if not build(p, spec, files.dir).violations:
                        break
                    proposer.reject(p)  # infeasible geometry costs no evaluation
                else:
                    raise RuntimeError(f"{method}: no geometry-feasible proposal in {MAX_GEOMETRY_TRIES} tries")
            geo = build(p, spec, files.dir)
            res, why = neuralfoil.evaluate(p, spec), "baseline" if not ledger else why_sample
        rec, rep = _record(gen, p, res, spec, ledger, why, str(files.dir), geo.coords_path)
        ledger.append(rec)
        files.append_record(rec)
        proposer.tell(p, rec)
        gen += 1
        if rep.terminal and rep.status == "PASS":
            term = "target_met"
            break
    meta = {
        "method": method,
        "llm_client": label,
        "is_mock": True,
        "spec": spec.model_dump(),
        "start": start.model_dump(),
        "start_seed": seed,
    }
    files.write_meta(meta)
    if write_report:
        _write_report({"spec": spec, "ledger": ledger, "started_at": t0}, files, term, _NoLLM(label, method))
    else:
        files.write_meta({"termination": term, "evals": len(ledger)})
    return {**meta, "termination": term, "evals": len(ledger), "wall_hours": (time.time() - t0) / 3600.0}


def random_search(
    spec: DesignSpec, start: WingParams, seed: int, run_dir: str | Path, write_report: bool = True
) -> dict:
    return search("random", spec, start, seed, run_dir, write_report)


def optuna_search(
    spec: DesignSpec, start: WingParams, seed: int, run_dir: str | Path, write_report: bool = True
) -> dict:
    return search("optuna", spec, start, seed, run_dir, write_report)
