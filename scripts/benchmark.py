"""Benchmark on the hard preset (FSAE 2027): hybrid vs LLM-only vs mock vs random search vs Optuna TPE.

    uv run python scripts/benchmark.py run --methods mock random optuna --parallel 3   # offline
    uv run python scripts/benchmark.py run --methods llm hybrid --parallel 5   # needs AEROSWARM_ANTHROPIC_API_KEY
    uv run python scripts/benchmark.py report                             # writes docs/BENCHMARK4.md

Arms: hybrid = real LLM, the Chief may hand a subspace to the inner optimizer (milestone 4); llm = real
LLM, inner optimizer disabled (LLM-only); mock = the rule-based MockClient, inner optimizer disabled;
mock_hybrid = MockClient that uses the inner optimizer (an offline check of the hybrid path, NOT an
LLM); random / optuna = the baselines. Every run: HARD_SPEC with max_evals 40 (the binding limit),
cost cap $4 and wall clock 1.5 h as safety caps, start = baselines.random_start(seed). Runs go to
runs/bench4/<method>_s<seed>/. Earlier benchmarks (runs/bench, bench2, bench3; docs/BENCHMARK.md) ran
under Formula Student 2026 and are not comparable.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from swarm.baselines import random_start, search
from swarm.briefs import near_target, screen_blocked
from swarm.critic.numeric import VALIDATION
from swarm.ledger import RunFiles
from swarm.llm.client import TraceLogger
from swarm.llm.mock import MockClient
from swarm.run import HARD_SPEC, run
from swarm.stats import quartiles, wilson_interval

SEEDS = (11, 22, 33, 44, 55, 66, 77, 88, 99, 110, 121, 132, 143, 154, 165)
METHODS = ("hybrid", "llm", "mock", "mock_hybrid", "random", "optuna")
REAL_LLM = ("hybrid", "llm")
MOCK_INNER_BUDGET = 8
SPEC = HARD_SPEC.model_copy(update={"max_evals": 40, "max_cost_usd": 4.0, "max_wall_hours": 1.5})
ROOT = Path("runs/bench4")
DOC = Path("docs/BENCHMARK4.md")


def one(job: tuple[str, int, str]) -> str:
    method, seed, root = job
    rid = f"{method}_s{seed}"
    d = Path(root) / rid
    if (d / "meta.json").exists() and "termination" in json.loads((d / "meta.json").read_text()):
        return f"{rid}: already finished, skipped (delete {d} to re-run)"
    if d.exists() and any(d.iterdir()):
        # an unfinished run: appending to its ledger/events (and its checkpoint thread) would mix two runs
        return f"{rid}: unfinished run directory {d} exists, skipped (move or delete it to re-run)"
    start = random_start(seed, SPEC)
    t0 = time.time()
    if method in ("random", "optuna"):
        search(method, SPEC, start, seed, Path(root) / rid)
    else:
        llm = None
        if method == "mock_hybrid":
            llm = MockClient(TraceLogger(RunFiles(Path(root) / rid).traces), inner_budget=MOCK_INNER_BUDGET)
        run(
            SPEC,
            start,
            run_id=rid,
            runs_root=root,
            llm=llm,
            which="anthropic" if method in REAL_LLM else "mock",
            preset="hard",
            start_seed=seed,
            inner_optimizer=method in ("hybrid", "mock_hybrid"),
        )
    meta_p = Path(root) / rid / "meta.json"
    meta = json.loads(meta_p.read_text())
    meta |= {"method": method, "bench_wall_s": round(time.time() - t0, 1)}
    meta_p.write_text(json.dumps(meta, indent=2, default=str))
    return f"{rid}: {meta['termination']} after {meta['evals']} evals, {meta['bench_wall_s']:.0f} s"


def cmd_run(methods: list[str], seeds: list[int], parallel: int, root: str) -> None:
    jobs = [(m, s, root) for m in methods for s in seeds]
    if parallel > 1:
        with Pool(parallel) as pool:
            for line in pool.imap_unordered(one, jobs):
                print(line, flush=True)
    else:
        for j in jobs:
            print(one(j), flush=True)


def _row(d: Path) -> dict | None:
    if not (d / "meta.json").exists():
        return None
    meta = json.loads((d / "meta.json").read_text())
    if "termination" not in meta:  # still running
        return None
    ledger = [json.loads(x) for x in (d / "ledger.jsonl").read_text().splitlines() if x]
    events = (
        [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines()] if (d / "events.jsonl").exists() else []
    )
    xf = sum(r["result"]["fidelity"] == "xfoil" for r in ledger)
    inner_cids = {r["result"]["cid"] for r in ledger if r.get("inner_optimizer")}
    usage = meta.get("llm_usage") or {}
    return {
        "method": meta.get("method"),
        "seed": meta.get("start_seed"),
        "termination": meta["termination"],
        "success": meta["termination"] == "target_met",
        "evals": meta["evals"],
        "xfoil_evals": xf,
        "cost": float(usage.get("cost_usd", 0.0) or 0.0),
        "calls": usage.get("calls", 0),
        "wall_h": (meta.get("limits") or {}).get("wall_hours") or meta.get("bench_wall_s", 0) / 3600,
        "best": meta.get("best_passing_cid"),
        "closest": meta.get("closest_candidate_cid"),
        "failing": (meta.get("closest_candidate_failing") or [""])[0],
        "blocked": sum(e.get("event") in ("promotion_blocked_by_screen", "direct_xfoil_screened_out") for e in events),
        "overrides": sum(e.get("event") in ("promotion_screen_override", "screen_override") for e in events),
        "deferred": sum(e.get("event") == "plateau_deferred" for e in events),
        "inner_runs": sum(e.get("event") == "inner_optimizer_finished" for e in events),
        "inner_evals": sum(bool(r.get("inner_optimizer")) for r in ledger),
        # XFoil evaluations of designs the inner optimizer found (promoted by the Chief), and whether the
        # passing design was one of them
        "inner_promoted": sum(r["result"]["fidelity"] == "xfoil" and r["result"]["cid"] in inner_cids for r in ledger),
        "inner_found_pass": meta.get("best_passing_cid") in inner_cids,
        # NeuralFoil designs in the promotion window that the screen failed (never promotable)
        "near_blocked": sum(screen_blocked(x) for x in near_target(RunFiles(d).read_ledger(), SPEC)),
        "start": meta.get("start"),
    }


def cmd_report(root: str) -> None:
    rows = [r for d in sorted(Path(root).glob("*_s*")) if (r := _row(d))]
    by = {m: sorted([r for r in rows if r["method"] == m], key=lambda r: r["seed"]) for m in METHODS}
    out = ["# Benchmark 4 (FSAE 2027): hybrid vs LLM-only vs mock vs random search vs Optuna TPE", ""]
    out += [
        f"Target Cl {SPEC.target_cl} ± {SPEC.cl_tol}, Cd ≤ {SPEC.cd_max}, Re {SPEC.reynolds:.0e}. Budget "
        f"{SPEC.max_evals} evaluations (the binding limit); safety caps ${SPEC.max_cost_usd:.0f} estimated LLM "
        f"cost and {SPEC.max_wall_hours} h wall clock per run. Starts: `baselines.random_start(seed)`, "
        f"{len(SEEDS)} seeds ({', '.join(map(str, SEEDS))}). Produced by `scripts/benchmark.py`; numbers from "
        "each run's meta.json / ledger.jsonl / events.jsonl. Rulebook FSAE 2027 v1.0 (thickness ≥ 0.123); "
        "earlier benchmarks (docs/BENCHMARK.md) ran under Formula Student 2026 and are not comparable.",
        "",
        "## Summary",
        "",
        "| method | seeds completed | success | 95% interval (Wilson) | evals to target, successes: median [IQR] "
        "| est. LLM cost / run: mean (total) | XFoil evals / run: mean [min–max] | wall clock / run (mean) "
        "| stopped on a safety cap |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in METHODS:
        # an invalid real-LLM run (e.g. aborted on API errors) is not a result: excluded, listed below
        rs = [r for r in by[m] if r["termination"] != "invalid_llm"]
        done = f"{len(rs)}/{len(SEEDS)}"
        if not rs:
            out.append(f"| {m} | {done} | not run | | | | | | |")
            continue
        ok = [r for r in rs if r["success"]]
        lo, hi = wilson_interval(len(ok), len(rs))
        if ok:
            q1, med, q3 = quartiles([float(r["evals"]) for r in ok])
            ev = f"{med:g} [{q1:g}–{q3:g}]"
        else:
            ev = "—"
        xf = [r["xfoil_evals"] for r in rs]
        caps = [f"s{r['seed']}: {r['termination']}" for r in rs if r["termination"] in ("cost_cap", "wall_clock")]
        out.append(
            f"| {m} | {done} | {len(ok)}/{len(rs)} ({100 * len(ok) / len(rs):.0f}%) | {100 * lo:.0f}–{100 * hi:.0f}% "
            f"| {ev} "
            f"| ${statistics.mean(r['cost'] for r in rs):.2f} (${sum(r['cost'] for r in rs):.2f}) "
            f"| {statistics.mean(xf):.1f} [{min(xf)}–{max(xf)}] "
            f"| {60 * statistics.mean(r['wall_h'] for r in rs):.1f} min "
            f"| {', '.join(caps) or 'none'} |"
        )
    out += [
        "",
        "## Per run",
        "",
        "| method | seed | termination | evals | XFoil evals | near-target designs failing the screen "
        "| blocked promotions / direct XFoil | screen overrides | plateaus deferred "
        "| inner runs (evals; XFoil of inner designs) | est. cost | wall clock | result |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in METHODS:
        for r in by[m]:
            res = f"PASS `{r['best']}`" if r["success"] else f"closest `{r['closest']}`: {r['failing']}"
            if r["inner_found_pass"]:
                res += " (found by the inner optimizer)"
            inner = f"{r['inner_runs']} ({r['inner_evals']}; {r['inner_promoted']})" if r["inner_runs"] else "-"
            out.append(
                f"| {m} | {r['seed']} | {r['termination']} | {r['evals']} | {r['xfoil_evals']} | {r['near_blocked']} "
                f"| {r['blocked']} | {r['overrides']} | {r['deferred']} | {inner} "
                f"| ${r['cost']:.2f} | {60 * r['wall_h']:.1f} min | {res} |"
            )
    out += [
        "",
        "## Methods",
        "",
        "- **hybrid**: the agent graph with the real LLM (`--llm anthropic`, the client's default model,",
        "  meta.json `llm_client`); the Chief may set mode `inner_optimizer`, which runs Optuna TPE",
        "  (`swarm/optim/inner_loop.py`, deterministic, no LLM) for 3–12 NeuralFoil evaluations over its",
        "  focus parameters within the trust region around the CAD base, warm-started from the ledger.",
        "  Every inner evaluation is a ledger record and counts toward the 40; the Chief decides promotions.",
        "- **llm**: the same graph and LLM with the inner optimizer disabled (LLM-only; the prompt says the",
        "  mode is disabled). LLM runs execute concurrently (one process per seed), so their wall clock",
        "  includes some CPU contention between XFoil solves.",
        "- **mock**: the same graph with `MockClient`, a deterministic rule-based stand-in (NOT an LLM):",
        "  damped least-norm steps on the NeuralFoil sensitivities, promote the best promotable design.",
        f"- **mock_hybrid**: `MockClient(inner_budget={MOCK_INNER_BUDGET})` with the inner optimizer allowed:",
        "  after two generations without improvement it hands its three most sensitive parameters (trust radius 0.15)",
        "  to the inner optimizer, then alternates. An offline check of the hybrid path, NOT an LLM.",
        "- **random**: `baselines.search('random')`: each evaluation promotes the best promotable design if",
        "  any (the pipeline's rule), else evaluates a uniform random sample of camber, position,",
        "  thickness and alpha over their bounds. Same geometry checks, NeuralFoil screen, XFoil ladder,",
        "  stall probe and validator as the graph.",
        "- **optuna**: `baselines.search('optuna')`: the same loop and gates with Optuna's TPE sampler",
        "  (seeded, Optuna defaults: 10 random start-up trials) in place of the uniform sample. It",
        "  minimizes the constraint violation the agents' parent selection uses (`ledger.violation`),",
        "  objective as a tie-break; the start is its first trial; XFoil results of promoted designs are",
        "  added as trials; geometry-infeasible proposals cost no evaluation.",
        "- Constraint violation (`ledger.violation`; parent selection in graph runs, Optuna's objective, the",
        "  inner optimizer's objective): since session 13 the screen's alpha+1/+2 TE-H warning counts as",
        "  separation at NeuralFoil (before, only the warning at alpha did). Not in earlier benchmarks.",
        "- An evaluation is one ledger record (a NeuralFoil or an XFoil result); stall-margin probes and",
        "  ladder retries are part of the XFoil evaluation they belong to, as in a run.",
        f"- NeuralFoil screen (all methods): d|Cl|/dα ≥ {VALIDATION.screen_min_dcl_dalpha} and suction-side TE H "
        f"< {VALIDATION.screen_h_probe_max} at alpha+1/+2, TE H < {VALIDATION.screen_h_sep} at alpha (session 10",
        "  cost-weighted calibration). The Chief may promote a screen-failed design with a logged",
        "  screen_override; the baselines never do.",
        "- Graph runs (hybrid, llm, mock, mock_hybrid): a declared plateau ends the run only after 80% of",
        "  the budget; earlier it triggers exploration (wider trust region, or a restart from a different",
        "  ledger region).",
    ]
    starts = next((by[m] for m in METHODS if by[m]), [])
    out += ["", "## Starts", "", "| seed | camber | position | thickness | alpha |", "|---|---|---|---|---|"]
    for r in starts:
        s = r["start"]
        out.append(
            f"| {r['seed']} | {s['main_camber']} | {s['main_camber_pos']} | {s['main_thickness']} | {s['alpha_deg']} |"
        )
    keep = ""
    if DOC.exists() and "## Observations" in DOC.read_text():  # hand-written; survives regeneration
        keep = "\n" + DOC.read_text()[DOC.read_text().index("## Observations") :]
    DOC.write_text("\n".join(out) + "\n" + keep)
    print(DOC.read_text())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--methods", nargs="+", choices=METHODS, required=True)
    r.add_argument("--seeds", nargs="+", type=int, default=list(SEEDS))
    r.add_argument("--parallel", type=int, default=1)
    r.add_argument("--root", default=str(ROOT))
    p = sub.add_parser("report")
    p.add_argument("--root", default=str(ROOT))
    a = ap.parse_args()
    if a.cmd == "run":
        cmd_run(a.methods, a.seeds, a.parallel, a.root)
    else:
        cmd_report(a.root)
    sys.exit(0)
