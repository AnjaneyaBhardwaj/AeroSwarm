"""Benchmark on the hard preset: real LLM vs mock vs random search, seeded random feasible starts.

    uv run python scripts/benchmark.py run --methods mock random          # offline, sequential
    uv run python scripts/benchmark.py run --methods llm --parallel 5     # needs AEROSWARM_ANTHROPIC_API_KEY
    uv run python scripts/benchmark.py report                             # writes docs/BENCHMARK.md

Every run: HARD_SPEC with max_evals 40 (the binding limit), cost cap $4 and wall clock 1.5 h as
safety caps, start = baselines.random_start(seed). Runs go to runs/bench/<method>_s<seed>/.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from swarm.baselines import random_search, random_start
from swarm.briefs import near_target, screen_blocked
from swarm.ledger import RunFiles
from swarm.run import HARD_SPEC, run

SEEDS = (11, 22, 33, 44, 55)
METHODS = ("llm", "mock", "random")
SPEC = HARD_SPEC.model_copy(update={"max_evals": 40, "max_cost_usd": 4.0, "max_wall_hours": 1.5})
ROOT = Path("runs/bench")
DOC = Path("docs/BENCHMARK.md")


def one(job: tuple[str, int, str]) -> str:
    method, seed, root = job
    rid = f"{method}_s{seed}"
    start = random_start(seed, SPEC)
    t0 = time.time()
    if method == "random":
        random_search(SPEC, start, seed, Path(root) / rid)
    else:
        run(
            SPEC,
            start,
            run_id=rid,
            runs_root=root,
            which="anthropic" if method == "llm" else "mock",
            preset="hard",
            start_seed=seed,
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
        # NeuralFoil designs in the promotion window that the screen failed (never promotable)
        "near_blocked": sum(screen_blocked(x) for x in near_target(RunFiles(d).read_ledger(), SPEC)),
        "start": meta.get("start"),
    }


def cmd_report(root: str) -> None:
    rows = [r for d in sorted(Path(root).glob("*_s*")) if (r := _row(d))]
    by = {m: sorted([r for r in rows if r["method"] == m], key=lambda r: r["seed"]) for m in METHODS}
    out = ["# Benchmark: hard preset, LLM vs mock vs random search", ""]
    out += [
        f"Target Cl {SPEC.target_cl} ± {SPEC.cl_tol}, Cd ≤ {SPEC.cd_max}, Re {SPEC.reynolds:.0e}. Budget "
        f"{SPEC.max_evals} evaluations (the binding limit); safety caps ${SPEC.max_cost_usd:.0f} estimated LLM "
        f"cost and {SPEC.max_wall_hours} h wall clock per run. Starts: `baselines.random_start(seed)`, seeds "
        f"{', '.join(map(str, SEEDS))}. Produced by `scripts/benchmark.py`; numbers from each run's "
        "meta.json / ledger.jsonl.",
        "",
        "## Summary",
        "",
        "| method | success | evals to target (median, successes) | XFoil evals / run (mean) "
        "| est. LLM cost / run (mean) | wall clock / run (mean) | stopped on a safety cap |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in METHODS:
        rs = by[m]
        if not rs:
            out.append(f"| {m} | not run | | | | | |")
            continue
        ok = [r for r in rs if r["success"]]
        med = f"{statistics.median([r['evals'] for r in ok]):g}" if ok else "—"
        caps = [f"s{r['seed']}: {r['termination']}" for r in rs if r["termination"] in ("cost_cap", "wall_clock")]
        out.append(
            f"| {m} | {len(ok)}/{len(rs)} | {med} | {statistics.mean(r['xfoil_evals'] for r in rs):.1f} "
            f"| ${statistics.mean(r['cost'] for r in rs):.2f} "
            f"| {60 * statistics.mean(r['wall_h'] for r in rs):.1f} min "
            f"| {', '.join(caps) or 'none'} |"
        )
    out += [
        "",
        "## Per run",
        "",
        "| method | seed | termination | evals | XFoil evals | near-target designs failing the screen "
        "| blocked promotions / direct XFoil | est. cost | wall clock | result |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in METHODS:
        for r in by[m]:
            res = f"PASS `{r['best']}`" if r["success"] else f"closest `{r['closest']}`: {r['failing']}"
            out.append(
                f"| {m} | {r['seed']} | {r['termination']} | {r['evals']} | {r['xfoil_evals']} | {r['near_blocked']} "
                f"| {r['blocked']} "
                f"| ${r['cost']:.2f} | {60 * r['wall_h']:.1f} min | {res} |"
            )
    out += [
        "",
        "## Methods",
        "",
        "- **llm**: the agent graph with the real LLM (`--llm anthropic`, the client's default model,",
        "  meta.json `llm_client`). Its runs were executed concurrently (one process per seed), so their",
        "  wall clock includes some CPU contention between XFoil solves.",
        "- **mock**: the same graph with `MockClient`, a deterministic rule-based stand-in (NOT an LLM):",
        "  damped least-norm steps on the NeuralFoil sensitivities, promote the best promotable design.",
        "- **random**: `baselines.random_search`: each evaluation promotes the best promotable design if",
        "  any (the pipeline's rule), else evaluates a uniform random sample of camber, position,",
        "  thickness and alpha over their bounds. Same geometry checks, NeuralFoil screen, XFoil ladder,",
        "  stall probe and validator as the graph.",
        "- An evaluation is one ledger record (a NeuralFoil or an XFoil result); stall-margin probes and",
        "  ladder retries are part of the XFoil evaluation they belong to, as in a run.",
        "- All methods use the session-9 NeuralFoil screen (slope >= 0.0575 and TE H < 3.85 at",
        "  alpha+1/+2), which keeps false passes near 5% but blocks about 43% of XFoil-feasible designs",
        "  near the target (docs/PROGRESS.md, session 9).",
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
