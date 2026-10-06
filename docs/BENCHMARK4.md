# Benchmark 4 (FSAE 2027): hybrid vs LLM-only vs mock vs random search vs Optuna TPE

Target Cl -1.83 ± 0.03, Cd ≤ 0.025, Re 3e+05. Budget 40 evaluations (the binding limit); safety caps $4 estimated LLM cost and 1.5 h wall clock per run. Starts: `baselines.random_start(seed)`, 15 seeds (11, 22, 33, 44, 55, 66, 77, 88, 99, 110, 121, 132, 143, 154, 165). Produced by `scripts/benchmark.py`; numbers from each run's meta.json / ledger.jsonl / events.jsonl. Rulebook FSAE 2027 v1.0 (thickness ≥ 0.123); earlier benchmarks (docs/BENCHMARK.md) ran under Formula Student 2026 and are not comparable.

## Summary

| method | seeds completed | success | 95% interval (Wilson) | evals to target, successes: median [IQR] | est. LLM cost / run: mean (total) | XFoil evals / run: mean [min–max] | wall clock / run (mean) | stopped on a safety cap |
|---|---|---|---|---|---|---|---|---|
| hybrid | 0/15 | not run | | | | | | |
| llm | 0/15 | not run | | | | | | |
| mock | 15/15 | 1/15 (7%) | 1–30% | 25 [25–25] | $0.00 ($0.00) | 0.1 [0–1] | 0.1 min | none |
| mock_hybrid | 15/15 | 1/15 (7%) | 1–30% | 24 [24–24] | $0.00 ($0.00) | 0.3 [0–2] | 0.1 min | none |
| random | 15/15 | 0/15 (0%) | 0–20% | — | $0.00 ($0.00) | 0.0 [0–0] | 0.1 min | none |
| optuna | 15/15 | 1/15 (7%) | 1–30% | 19 [19–19] | $0.00 ($0.00) | 0.5 [0–2] | 0.1 min | none |

## Per run

| method | seed | termination | evals | XFoil evals | near-target designs failing the screen | blocked promotions / direct XFoil | screen overrides | plateaus deferred | inner runs (evals; XFoil of inner designs) | est. cost | wall clock | result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mock | 11 | plateau | 32 | 0 | 22 | 0 | 0 | 18 | - | $0.00 | 0.1 min | closest `7b2dc25927`: NeuralFoil stall screen: d|Cl|/dalpha 0.021/deg < 0.055 |
| mock | 22 | plateau | 32 | 0 | 6 | 0 | 0 | 2 | - | $0.00 | 0.1 min | closest `54a0b376ea`: NeuralFoil stall screen: d|Cl|/dalpha 0.015/deg < 0.055 |
| mock | 33 | plateau | 32 | 0 | 9 | 0 | 0 | 18 | - | $0.00 | 0.1 min | closest `245f0397f8`: NeuralFoil stall screen: d|Cl|/dalpha 0.018/deg < 0.055 |
| mock | 44 | plateau | 37 | 0 | 18 | 0 | 0 | 16 | - | $0.00 | 0.1 min | closest `4c0ddf986a`: NeuralFoil stall screen: d|Cl|/dalpha 0.030/deg < 0.055 |
| mock | 55 | plateau | 32 | 0 | 16 | 0 | 0 | 11 | - | $0.00 | 0.1 min | closest `eca91e7c36`: NeuralFoil stall screen: d|Cl|/dalpha 0.015/deg < 0.055 |
| mock | 66 | plateau | 32 | 0 | 11 | 0 | 0 | 9 | - | $0.00 | 0.1 min | closest `a38289adb9`: NeuralFoil stall screen: d|Cl|/dalpha 0.012/deg < 0.055 |
| mock | 77 | plateau | 32 | 0 | 18 | 0 | 0 | 8 | - | $0.00 | 0.1 min | closest `489c7406c6`: NeuralFoil stall screen: d|Cl|/dalpha 0.034/deg < 0.055 |
| mock | 88 | eval_budget | 40 | 0 | 8 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `27bd796cd4`: NeuralFoil stall screen: d|Cl|/dalpha 0.033/deg < 0.055 |
| mock | 99 | plateau | 32 | 0 | 17 | 0 | 0 | 9 | - | $0.00 | 0.1 min | closest `d6e09af592`: NeuralFoil stall screen: d|Cl|/dalpha 0.048/deg < 0.055 |
| mock | 110 | plateau | 34 | 0 | 26 | 0 | 0 | 4 | - | $0.00 | 0.1 min | closest `b16b30fa06`: NeuralFoil stall screen: d|Cl|/dalpha 0.055/deg < 0.055 |
| mock | 121 | plateau | 32 | 0 | 23 | 0 | 0 | 6 | - | $0.00 | 0.1 min | closest `fe3ee1bba4`: NeuralFoil stall screen: d|Cl|/dalpha 0.051/deg < 0.055 |
| mock | 132 | plateau | 32 | 0 | 11 | 0 | 0 | 8 | - | $0.00 | 0.1 min | closest `779bc4345e`: NeuralFoil stall screen: d|Cl|/dalpha 0.013/deg < 0.055 |
| mock | 143 | plateau | 35 | 0 | 15 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `ace84f2c65`: NeuralFoil stall screen: d|Cl|/dalpha -0.005/deg < 0.055 |
| mock | 154 | target_met | 25 | 1 | 8 | 0 | 0 | 12 | - | $0.00 | 0.1 min | PASS `9c299ae39d` |
| mock | 165 | plateau | 32 | 0 | 9 | 0 | 0 | 7 | - | $0.00 | 0.1 min | closest `f26e320fe0`: target box: Cd 0.02518 > cd_max 0.025 |
| mock_hybrid | 11 | eval_budget | 40 | 0 | 22 | 0 | 0 | 0 | 4 (27; 0) | $0.00 | 0.1 min | closest `21b2c0452b`: NeuralFoil stall screen: d|Cl|/dalpha 0.036/deg < 0.055 |
| mock_hybrid | 22 | eval_budget | 40 | 0 | 12 | 0 | 0 | 0 | 4 (28; 0) | $0.00 | 0.1 min | closest `e1e1de2bb0`: NeuralFoil stall screen: d|Cl|/dalpha 0.014/deg < 0.055 |
| mock_hybrid | 33 | eval_budget | 40 | 0 | 24 | 0 | 0 | 0 | 4 (26; 0) | $0.00 | 0.1 min | closest `ac5f3e6bf3`: NeuralFoil stall screen: d|Cl|/dalpha 0.037/deg < 0.055 |
| mock_hybrid | 44 | eval_budget | 40 | 0 | 24 | 0 | 0 | 0 | 4 (27; 0) | $0.00 | 0.1 min | closest `33f4aebeb8`: NeuralFoil stall screen: d|Cl|/dalpha 0.032/deg < 0.055 |
| mock_hybrid | 55 | eval_budget | 40 | 0 | 20 | 0 | 0 | 0 | 4 (27; 0) | $0.00 | 0.1 min | closest `f751d7f45a`: NeuralFoil stall screen: d|Cl|/dalpha 0.039/deg < 0.055 |
| mock_hybrid | 66 | eval_budget | 40 | 0 | 14 | 0 | 0 | 0 | 4 (25; 0) | $0.00 | 0.1 min | closest `b8fb314825`: NeuralFoil stall screen: d|Cl|/dalpha 0.010/deg < 0.055 |
| mock_hybrid | 77 | eval_budget | 40 | 0 | 19 | 0 | 0 | 0 | 4 (25; 0) | $0.00 | 0.1 min | closest `72a5fb1adf`: NeuralFoil stall screen: d|Cl|/dalpha 0.051/deg < 0.055 |
| mock_hybrid | 88 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | 2 (16; 0) | $0.00 | 0.1 min | closest `0c3f189e15`: target box: Cd 0.02570 > cd_max 0.025 |
| mock_hybrid | 99 | eval_budget | 40 | 2 | 9 | 2 | 0 | 0 | 4 (26; 2) | $0.00 | 0.1 min | closest `836309ab67`: stall_margin: TE separation within the probe range (x/c 0.99 at 11.1929°) |
| mock_hybrid | 110 | eval_budget | 40 | 1 | 23 | 1 | 0 | 0 | 4 (26; 1) | $0.00 | 0.1 min | closest `143773ec13`: target box: Cl -1.7878 is 0.0422 from -1.83 (tol 0.03) |
| mock_hybrid | 121 | eval_budget | 40 | 0 | 14 | 0 | 0 | 0 | 4 (28; 0) | $0.00 | 0.1 min | closest `bd176e7bea`: NeuralFoil stall screen: d|Cl|/dalpha 0.045/deg < 0.055 |
| mock_hybrid | 132 | eval_budget | 40 | 1 | 10 | 0 | 0 | 0 | 3 (22; 1) | $0.00 | 0.1 min | closest `cda5762a43`: target box: Cl -1.7846 is 0.0454 from -1.83 (tol 0.03) |
| mock_hybrid | 143 | eval_budget | 40 | 0 | 21 | 0 | 0 | 0 | 3 (18; 0) | $0.00 | 0.1 min | closest `43d12faa36`: NeuralFoil stall screen: d|Cl|/dalpha 0.009/deg < 0.055 |
| mock_hybrid | 154 | target_met | 24 | 1 | 7 | 0 | 0 | 0 | 2 (16; 1) | $0.00 | 0.0 min | PASS `0a36867557` (found by the inner optimizer) |
| mock_hybrid | 165 | eval_budget | 40 | 0 | 4 | 0 | 0 | 0 | 2 (13; 0) | $0.00 | 0.1 min | closest `6a70485682`: NeuralFoil separation warning at alpha+1/+2: suction-side TE H 4.36, 5.00 (limit 4.35) |
| random | 11 | eval_budget | 40 | 0 | 1 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `f039c40fe3`: NeuralFoil stall screen: d|Cl|/dalpha 0.041/deg < 0.055 |
| random | 22 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `925ccc3a81`: target box: Cl -1.8650 is 0.0350 from -1.83 (tol 0.03) |
| random | 33 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `234ebbc766`: target box: Cl -1.5852 is 0.2448 from -1.83 (tol 0.03) |
| random | 44 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `bb5cf5da87`: target box: Cd 0.03012 > cd_max 0.025 |
| random | 55 | eval_budget | 40 | 0 | 1 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `ca69f8c369`: target box: Cl -1.7840 is 0.0460 from -1.83 (tol 0.03) |
| random | 66 | eval_budget | 40 | 0 | 2 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `2e0c7cb576`: target box: Cl -1.7896 is 0.0404 from -1.83 (tol 0.03) |
| random | 77 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `97b08e6437`: target box: Cl -1.9277 is 0.0977 from -1.83 (tol 0.03) |
| random | 88 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `a43eefb2b1`: target box: Cl -1.7685 is 0.0615 from -1.83 (tol 0.03) |
| random | 99 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `7243cd5430`: target box: Cl -1.7645 is 0.0655 from -1.83 (tol 0.03) |
| random | 110 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.0 min | closest `5a0415162a`: target box: Cl -1.7378 is 0.0922 from -1.83 (tol 0.03) |
| random | 121 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `0592ee56f6`: target box: Cd 0.02936 > cd_max 0.025 |
| random | 132 | eval_budget | 40 | 0 | 1 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `b762ea19da`: target box: Cl -1.7819 is 0.0481 from -1.83 (tol 0.03) |
| random | 143 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `71b3c73159`: target box: Cl -1.7831 is 0.0469 from -1.83 (tol 0.03) |
| random | 154 | eval_budget | 40 | 0 | 1 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `cc90e149e0`: NeuralFoil stall screen: d|Cl|/dalpha -0.002/deg < 0.055 |
| random | 165 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `3786053684`: target box: Cl -1.6566 is 0.1734 from -1.83 (tol 0.03) |
| optuna | 11 | eval_budget | 40 | 1 | 8 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `0cbcfd2180`: target box: Cl -1.7905 is 0.0395 from -1.83 (tol 0.03) |
| optuna | 22 | eval_budget | 40 | 0 | 9 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `69041e13e4`: NeuralFoil stall screen: d|Cl|/dalpha 0.039/deg < 0.055 |
| optuna | 33 | eval_budget | 40 | 1 | 4 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `4c3c441458`: stall_margin: TE separation within the probe range (x/c 0.99 at 11.3654°) |
| optuna | 44 | eval_budget | 40 | 0 | 5 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `27709e4040`: NeuralFoil stall screen: d|Cl|/dalpha 0.040/deg < 0.055 |
| optuna | 55 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `d60f6ecae9`: target box: Cd 0.02657 > cd_max 0.025 |
| optuna | 66 | eval_budget | 40 | 0 | 2 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `89e0381929`: target box: Cl -1.7984 is 0.0316 from -1.83 (tol 0.03) |
| optuna | 77 | target_met | 19 | 1 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | PASS `80b02f02da` |
| optuna | 88 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `5784312676`: target box: Cl -1.7730 is 0.0570 from -1.83 (tol 0.03) |
| optuna | 99 | eval_budget | 40 | 1 | 3 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `ce6ee813f1`: target box: Cl -1.7809 is 0.0491 from -1.83 (tol 0.03) |
| optuna | 110 | eval_budget | 40 | 0 | 7 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `80c926e40e`: NeuralFoil stall screen: d|Cl|/dalpha 0.021/deg < 0.055 |
| optuna | 121 | eval_budget | 40 | 2 | 1 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `dec9aa5fb8`: stall_margin: TE separation within the probe range (x/c 0.99 at 11.3557°) |
| optuna | 132 | eval_budget | 40 | 1 | 4 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `84bd6c5e45`: target box: Cl -1.7898 is 0.0402 from -1.83 (tol 0.03) |
| optuna | 143 | eval_budget | 40 | 0 | 2 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `97960424bc`: target box: Cd 0.02502 > cd_max 0.025 |
| optuna | 154 | eval_budget | 40 | 1 | 3 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `a9fb8f7199`: target box: Cd 0.02550 > cd_max 0.025 |
| optuna | 165 | eval_budget | 40 | 0 | 9 | 0 | 0 | 0 | - | $0.00 | 0.1 min | closest `8bad60f1d5`: NeuralFoil stall screen: d|Cl|/dalpha 0.038/deg < 0.055 |

## Methods

- **hybrid**: the agent graph with the real LLM (`--llm anthropic`, the client's default model,
  meta.json `llm_client`); the Chief may set mode `inner_optimizer`, which runs Optuna TPE
  (`swarm/optim/inner_loop.py`, deterministic, no LLM) for 3–12 NeuralFoil evaluations over its
  focus parameters within the trust region around the CAD base, warm-started from the ledger.
  Every inner evaluation is a ledger record and counts toward the 40; the Chief decides promotions.
- **llm**: the same graph and LLM with the inner optimizer disabled (LLM-only; the prompt says the
  mode is disabled). LLM runs execute concurrently (one process per seed), so their wall clock
  includes some CPU contention between XFoil solves.
- **mock**: the same graph with `MockClient`, a deterministic rule-based stand-in (NOT an LLM):
  damped least-norm steps on the NeuralFoil sensitivities, promote the best promotable design.
- **mock_hybrid**: `MockClient(inner_budget=8)` with the inner optimizer allowed:
  after two generations without improvement it hands its three most sensitive parameters (trust radius 0.15)
  to the inner optimizer, then alternates. An offline check of the hybrid path, NOT an LLM.
- **random**: `baselines.search('random')`: each evaluation promotes the best promotable design if
  any (the pipeline's rule), else evaluates a uniform random sample of camber, position,
  thickness and alpha over their bounds. Same geometry checks, NeuralFoil screen, XFoil ladder,
  stall probe and validator as the graph.
- **optuna**: `baselines.search('optuna')`: the same loop and gates with Optuna's TPE sampler
  (seeded, Optuna defaults: 10 random start-up trials) in place of the uniform sample. It
  minimizes the constraint violation the agents' parent selection uses (`ledger.violation`),
  objective as a tie-break; the start is its first trial; XFoil results of promoted designs are
  added as trials; geometry-infeasible proposals cost no evaluation.
- An evaluation is one ledger record (a NeuralFoil or an XFoil result); stall-margin probes and
  ladder retries are part of the XFoil evaluation they belong to, as in a run.
- NeuralFoil screen (all methods): d|Cl|/dα ≥ 0.055 and suction-side TE H < 4.35 at alpha+1/+2, TE H < 4.25 at alpha (session 10
  cost-weighted calibration). The Chief may promote a screen-failed design with a logged
  screen_override; the baselines never do.
- Graph runs (hybrid, llm, mock, mock_hybrid): a declared plateau ends the run only after 80% of
  the budget; earlier it triggers exploration (wider trust region, or a restart from a different
  ledger region).

## Starts

| seed | camber | position | thickness | alpha |
|---|---|---|---|---|
| 11 | 0.0603 | 0.405 | 0.1617 | 6.7852 |
| 22 | 0.0413 | 0.5951 | 0.1652 | 11.3914 |
| 33 | 0.0399 | 0.4274 | 0.1708 | 2.068 |
| 44 | 0.061 | 0.4466 | 0.1755 | 4.5824 |
| 55 | 0.0443 | 0.5013 | 0.1504 | 13.1534 |
| 66 | 0.0414 | 0.5635 | 0.1592 | 6.4756 |
| 77 | 0.0287 | 0.3561 | 0.1601 | -0.5472 |
| 88 | 0.0186 | 0.4813 | 0.1489 | 9.0219 |
| 99 | 0.0455 | 0.426 | 0.1312 | 13.555 |
| 110 | 0.0837 | 0.405 | 0.1513 | 6.0356 |
| 121 | 0.057 | 0.3192 | 0.1624 | 7.2916 |
| 132 | 0.0128 | 0.5219 | 0.1545 | 12.1179 |
| 143 | 0.0372 | 0.5907 | 0.1306 | 8.4688 |
| 154 | 0.0817 | 0.2316 | 0.1326 | 12.0087 |
| 165 | 0.0416 | 0.431 | 0.1571 | 13.0819 |

## Observations

Offline arms only (session 13); the hybrid and llm arms wait for the user's go-ahead. All arms include the session-13
fix to `ledger.violation` (the screen's alpha+1/+2 TE-H warning now counts as separation at NeuralFoil), which
changes parent selection (mock) and Optuna's objective; the numbers are not comparable with docs/BENCHMARK.md for
that reason as well as the rulebook.

- Successes: mock 1/15 (seed 154, 25 evals), mock_hybrid 1/15 (seed 154, 24 evals, the passing design found by an
  inner run), Optuna 1/15 (seed 77, 19 evals), random 0/15. With 15 seeds the intervals (1–30%) overlap: the
  offline arms do not separate.
- XFoil is rare in every arm (mean 0–0.5 XFoil evaluations per run): designs near the target at NeuralFoil mostly
  fail the screen (column "near-target designs failing the screen"), and none of these arms overrides it.
- mock: 13 of 15 runs declared a plateau at 32 evaluations (the earliest allowed); seed 88 used the budget.
- mock_hybrid (a check of the hybrid path, not an LLM): 52 inner runs, 350 of its 600 evaluations; 4–33 warm-start
  designs per run (mean 13.8); 27 of 52 improved on the base design's value; 80 inner designs landed in the target box
  at NeuralFoil, of which 9 passed the screen (promotable); 5 were promoted (one passed, one failed the stall probe,
  three failed XFoil's box). Before the inner run kept the last evaluation free, two promotable designs were stranded
  at the end of the budget (seeds 110 and 132); both are promoted in this table.
