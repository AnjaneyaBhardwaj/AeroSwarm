# Benchmark: hard preset, LLM vs mock vs random search

Target Cl -1.83 ± 0.03, Cd ≤ 0.025, Re 3e+05. Budget 40 evaluations (the binding limit); safety caps $4 estimated LLM cost and 1.5 h wall clock per run. Starts: `baselines.random_start(seed)`, seeds 11, 22, 33, 44, 55. Produced by `scripts/benchmark.py`; numbers from each run's meta.json / ledger.jsonl.

## Summary

| method | success | evals to target (median, successes) | XFoil evals / run (mean) | est. LLM cost / run (mean) | wall clock / run (mean) | stopped on a safety cap |
|---|---|---|---|---|---|---|
| llm | 1/5 | 17 | 0.2 | $1.57 | 18.1 min | none |
| mock | 0/5 | — | 0.0 | $0.00 | 0.1 min | none |
| random | 0/5 | — | 0.0 | $0.00 | 0.1 min | none |

## Per run

| method | seed | termination | evals | XFoil evals | near-target designs failing the screen | blocked promotions / direct XFoil | est. cost | wall clock | result |
|---|---|---|---|---|---|---|---|---|---|
| llm | 11 | plateau | 16 | 0 | 5 | 1 | $1.28 | 15.0 min | closest `7fadb78f15`: NeuralFoil stall screen: d|Cl|/dalpha 0.022/deg < 0.0575 |
| llm | 22 | plateau | 20 | 0 | 0 | 0 | $1.33 | 14.5 min | closest `45dce69fe9`: target box: Cl -1.7693 is 0.0607 from -1.83 (tol 0.03) |
| llm | 33 | plateau | 28 | 0 | 8 | 7 | $2.45 | 29.5 min | closest `c01b22d3be`: NeuralFoil stall screen: d|Cl|/dalpha 0.050/deg < 0.0575 |
| llm | 44 | target_met | 17 | 1 | 5 | 0 | $1.10 | 12.1 min | PASS `1449e37232` |
| llm | 55 | plateau | 24 | 0 | 8 | 0 | $1.71 | 19.2 min | closest `0e250841f8`: NeuralFoil stall screen: d|Cl|/dalpha 0.035/deg < 0.0575 |
| mock | 11 | plateau | 12 | 0 | 7 | 0 | $0.00 | 0.1 min | closest `91a492198d`: NeuralFoil stall screen: d|Cl|/dalpha 0.036/deg < 0.0575 |
| mock | 22 | plateau | 30 | 0 | 6 | 0 | $0.00 | 0.1 min | closest `54a0b376ea`: NeuralFoil stall screen: d|Cl|/dalpha 0.015/deg < 0.0575 |
| mock | 33 | plateau | 14 | 0 | 7 | 0 | $0.00 | 0.1 min | closest `245f0397f8`: NeuralFoil stall screen: d|Cl|/dalpha 0.018/deg < 0.0575 |
| mock | 44 | plateau | 22 | 0 | 9 | 0 | $0.00 | 0.1 min | closest `43bbea9e7d`: NeuralFoil stall screen: d|Cl|/dalpha 0.037/deg < 0.0575 |
| mock | 55 | plateau | 39 | 0 | 22 | 0 | $0.00 | 0.1 min | closest `2f23ad0689`: NeuralFoil stall screen: d|Cl|/dalpha -0.069/deg < 0.0575 |
| random | 11 | eval_budget | 40 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `eea260c0d3`: target box: Cl -1.7252 is 0.1048 from -1.83 (tol 0.03) |
| random | 22 | eval_budget | 40 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `925ccc3a81`: target box: Cl -1.8650 is 0.0350 from -1.83 (tol 0.03) |
| random | 33 | eval_budget | 40 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `57ede32033`: target box: Cl -1.6599 is 0.1701 from -1.83 (tol 0.03) |
| random | 44 | eval_budget | 40 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `4c7f6c4643`: target box: Cl -1.7392 is 0.0908 from -1.83 (tol 0.03) |
| random | 55 | eval_budget | 40 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `779593f024`: target box: Cl -1.7267 is 0.1033 from -1.83 (tol 0.03) |

## Methods

- **llm**: the agent graph with the real LLM (`--llm anthropic`, the client's default model,
  meta.json `llm_client`). Its runs were executed concurrently (one process per seed), so their
  wall clock includes some CPU contention between XFoil solves.
- **mock**: the same graph with `MockClient`, a deterministic rule-based stand-in (NOT an LLM):
  damped least-norm steps on the NeuralFoil sensitivities, promote the best promotable design.
- **random**: `baselines.random_search`: each evaluation promotes the best promotable design if
  any (the pipeline's rule), else evaluates a uniform random sample of camber, position,
  thickness and alpha over their bounds. Same geometry checks, NeuralFoil screen, XFoil ladder,
  stall probe and validator as the graph.
- An evaluation is one ledger record (a NeuralFoil or an XFoil result); stall-margin probes and
  ladder retries are part of the XFoil evaluation they belong to, as in a run.
- All methods use the session-9 NeuralFoil screen (slope >= 0.0575 and TE H < 3.85 at
  alpha+1/+2), which keeps false passes near 5% but blocks about 43% of XFoil-feasible designs
  near the target (docs/PROGRESS.md, session 9).

## Starts

| seed | camber | position | thickness | alpha |
|---|---|---|---|---|
| 11 | 0.0853 | 0.4488 | 0.1169 | 6.1822 |
| 22 | 0.0413 | 0.5951 | 0.1652 | 11.3914 |
| 33 | 0.0399 | 0.4274 | 0.1708 | 2.068 |
| 44 | 0.011 | 0.3032 | 0.1206 | 13.5069 |
| 55 | 0.0749 | 0.5483 | 0.1018 | 1.6816 |

## Observations (hand-written from the run files, session 9; `scripts/benchmark.py report` keeps this section)

- **LLM 1/5, mock 0/5, random 0/5.** The LLM success (seed 44) took 17 evaluations, $1.10 and 12 min:
  `1449e37232` m 0.09, p 0.312, t 0.1304, α 8.557, XFoil Cl −1.8219, Cd 0.02408, margin 0.059. The
  memo that promoted it credits moving camber position forward to clear the screen.
- **Evaluations did not bind for the LLM either: 4 of 5 LLM runs declared a plateau** at 16, 20, 24 and
  28 evaluations with budget left (the Chief prompt allows a plateau after three non-improving
  hypotheses). Their final memos describe a trade-off they could not break: raising Cl to the target
  pushes the NeuralFoil stall slope under 0.0575, backing off undershoots Cl. All four closest
  designs sit on the camber bound (m 0.09) with camber position 0.40–0.54; the passing designs
  found so far (this run, live run 2, the gated sweep's box) are at p 0.30–0.36.
- **No run stopped on a safety cap.** Highest LLM cost $2.45 (seed 33, cap $4), longest 29.5 min (cap 1.5 h).
- **XFoil was almost never reached**: 1 XFoil evaluation in 25 runs (the seed-44 promotion). The mock's
  alpha-led steps stay in the stall region (every near-target design fails the screen); uniform random
  search never landed in the promotion window in 40 samples (closest |ΔCl| 0.035).
- **The screen did not cost any method a success.** Counterfactual: every near-target design the screen
  failed was run through the real XFoil gate. Mock: 0 of 51 would pass. LLM: 2 of 26 would pass, both in
  seed 44, which succeeded anyway. In the four failed LLM runs all 21 would also fail XFoil.
- **Guards fired as intended**: 10 duplicate rejections across the LLM runs, 3 of them near-duplicates
  (seeds 11 and 33) that the old exact-cid check would have let through as new evaluations; seed 33 had
  2 CAD overrides, both adopted by the Chief the next generation (no deadlock coercion needed).
- One sample per seed; the LLM is not deterministic. Wall clock for the LLM rows includes running the five
  seeds concurrently.
