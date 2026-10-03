# Benchmark: hard preset, LLM vs mock vs random search vs Optuna TPE

Target Cl -1.83 ± 0.03, Cd ≤ 0.025, Re 3e+05. Budget 40 evaluations (the binding limit); safety caps $4 estimated LLM cost and 1.5 h wall clock per run. Starts: `baselines.random_start(seed)`, 15 seeds (11, 22, 33, 44, 55, 66, 77, 88, 99, 110, 121, 132, 143, 154, 165). Produced by `scripts/benchmark.py`; numbers from each run's meta.json / ledger.jsonl / events.jsonl.

## Summary

| method | seeds completed | success | 95% interval (Wilson) | evals to target, successes: median [IQR] | est. LLM cost / run: mean (total) | XFoil evals / run: mean [min–max] | wall clock / run (mean) | stopped on a safety cap |
|---|---|---|---|---|---|---|---|---|
| llm | 1/15 | 1/1 (100%) | 21–100% | 19 [19–19] | $1.22 ($1.22) | 5.0 [5–5] | 13.2 min | none |
| mock | 15/15 | 0/15 (0%) | 0–20% | — | $0.00 ($0.00) | 0.0 [0–0] | 0.1 min | none |
| random | 15/15 | 0/15 (0%) | 0–20% | — | $0.00 ($0.00) | 0.0 [0–0] | 0.1 min | none |
| optuna | 15/15 | 2/15 (13%) | 4–38% | 28.5 [26.25–30.75] | $0.00 ($0.00) | 0.2 [0–1] | 0.1 min | none |

## Per run

| method | seed | termination | evals | XFoil evals | near-target designs failing the screen | blocked promotions / direct XFoil | screen overrides | plateaus deferred | est. cost | wall clock | result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| llm | 44 | target_met | 19 | 5 | 2 | 0 | 3 | 0 | $1.22 | 13.2 min | PASS `7d78d095ac` |
| mock | 11 | eval_budget | 40 | 0 | 26 | 0 | 0 | 20 | $0.00 | 0.1 min | closest `862d9933ef`: NeuralFoil stall screen: d|Cl|/dalpha -0.027/deg < 0.055 |
| mock | 22 | plateau | 32 | 0 | 6 | 0 | 0 | 2 | $0.00 | 0.1 min | closest `54a0b376ea`: NeuralFoil stall screen: d|Cl|/dalpha 0.015/deg < 0.055 |
| mock | 33 | plateau | 32 | 0 | 9 | 0 | 0 | 18 | $0.00 | 0.1 min | closest `245f0397f8`: NeuralFoil stall screen: d|Cl|/dalpha 0.018/deg < 0.055 |
| mock | 44 | plateau | 32 | 0 | 12 | 0 | 0 | 10 | $0.00 | 0.1 min | closest `43bbea9e7d`: NeuralFoil stall screen: d|Cl|/dalpha 0.037/deg < 0.055 |
| mock | 55 | plateau | 39 | 0 | 22 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `2f23ad0689`: NeuralFoil stall screen: d|Cl|/dalpha -0.069/deg < 0.055 |
| mock | 66 | plateau | 32 | 0 | 11 | 0 | 0 | 9 | $0.00 | 0.1 min | closest `a38289adb9`: NeuralFoil stall screen: d|Cl|/dalpha 0.012/deg < 0.055 |
| mock | 77 | plateau | 32 | 0 | 19 | 0 | 0 | 11 | $0.00 | 0.1 min | closest `255579d810`: NeuralFoil stall screen: d|Cl|/dalpha 0.022/deg < 0.055 |
| mock | 88 | eval_budget | 40 | 0 | 8 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `27bd796cd4`: NeuralFoil stall screen: d|Cl|/dalpha 0.033/deg < 0.055 |
| mock | 99 | plateau | 32 | 0 | 17 | 0 | 0 | 9 | $0.00 | 0.1 min | closest `d6e09af592`: NeuralFoil stall screen: d|Cl|/dalpha 0.048/deg < 0.055 |
| mock | 110 | plateau | 34 | 0 | 26 | 0 | 0 | 4 | $0.00 | 0.1 min | closest `b16b30fa06`: NeuralFoil stall screen: d|Cl|/dalpha 0.055/deg < 0.055 |
| mock | 121 | plateau | 32 | 0 | 23 | 0 | 0 | 6 | $0.00 | 0.1 min | closest `fe3ee1bba4`: NeuralFoil stall screen: d|Cl|/dalpha 0.051/deg < 0.055 |
| mock | 132 | plateau | 38 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `0e3c1e8a23`: target box: Cl -1.3687 is 0.4613 from -1.83 (tol 0.03) |
| mock | 143 | plateau | 32 | 0 | 9 | 0 | 0 | 10 | $0.00 | 0.1 min | closest `925ea82818`: NeuralFoil stall screen: d|Cl|/dalpha 0.004/deg < 0.055 |
| mock | 154 | plateau | 32 | 0 | 15 | 0 | 0 | 15 | $0.00 | 0.1 min | closest `02c66f8a21`: NeuralFoil stall screen: d|Cl|/dalpha -0.063/deg < 0.055 |
| mock | 165 | plateau | 32 | 0 | 9 | 0 | 0 | 7 | $0.00 | 0.1 min | closest `f26e320fe0`: target box: Cd 0.02518 > cd_max 0.025 |
| random | 11 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `eea260c0d3`: target box: Cl -1.7252 is 0.1048 from -1.83 (tol 0.03) |
| random | 22 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `925ccc3a81`: target box: Cl -1.8650 is 0.0350 from -1.83 (tol 0.03) |
| random | 33 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `57ede32033`: target box: Cl -1.6599 is 0.1701 from -1.83 (tol 0.03) |
| random | 44 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `4c7f6c4643`: target box: Cl -1.7392 is 0.0908 from -1.83 (tol 0.03) |
| random | 55 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `779593f024`: target box: Cl -1.7267 is 0.1033 from -1.83 (tol 0.03) |
| random | 66 | eval_budget | 40 | 0 | 1 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `acdb591955`: target box: Cl -1.7860 is 0.0440 from -1.83 (tol 0.03) |
| random | 77 | eval_budget | 40 | 0 | 2 | 0 | 0 | 0 | $0.00 | 0.0 min | closest `d467f15812`: NeuralFoil stall screen: d|Cl|/dalpha 0.047/deg < 0.055 |
| random | 88 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `38b612efe3`: target box: Cl -1.6787 is 0.1513 from -1.83 (tol 0.03) |
| random | 99 | eval_budget | 40 | 0 | 1 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `a2dce3d91c`: target box: Cl -1.7987 is 0.0313 from -1.83 (tol 0.03) |
| random | 110 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.0 min | closest `5a0415162a`: target box: Cl -1.7378 is 0.0922 from -1.83 (tol 0.03) |
| random | 121 | eval_budget | 40 | 0 | 1 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `7e96c3981a`: target box: Cl -1.8647 is 0.0347 from -1.83 (tol 0.03) |
| random | 132 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.0 min | closest `e41f6214aa`: target box: Cd 0.02598 > cd_max 0.025 |
| random | 143 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `e10283e3fd`: target box: Cd 0.03154 > cd_max 0.025 |
| random | 154 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `363389deeb`: target box: Cl -1.7469 is 0.0831 from -1.83 (tol 0.03) |
| random | 165 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `ac5d207779`: target box: Cl -1.7789 is 0.0511 from -1.83 (tol 0.03) |
| optuna | 11 | eval_budget | 40 | 0 | 6 | 0 | 0 | 0 | $0.00 | 0.0 min | closest `ec36b4c498`: target box: Cd 0.02559 > cd_max 0.025 |
| optuna | 22 | eval_budget | 40 | 0 | 7 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `a5700ca025`: NeuralFoil stall screen: d|Cl|/dalpha 0.030/deg < 0.055 |
| optuna | 33 | target_met | 33 | 1 | 1 | 0 | 0 | 0 | $0.00 | 0.1 min | PASS `dac398b9df` |
| optuna | 44 | eval_budget | 40 | 0 | 1 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `2267a99c3b`: NeuralFoil stall screen: d|Cl|/dalpha 0.047/deg < 0.055 |
| optuna | 55 | eval_budget | 40 | 0 | 4 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `46e9f747ad`: NeuralFoil stall screen: d|Cl|/dalpha 0.033/deg < 0.055 |
| optuna | 66 | eval_budget | 40 | 0 | 1 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `3cb8eb34e3`: NeuralFoil stall screen: d|Cl|/dalpha 0.024/deg < 0.055 |
| optuna | 77 | eval_budget | 40 | 1 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `b5e4707d27`: target box: Cd 0.02578 > cd_max 0.025 |
| optuna | 88 | eval_budget | 40 | 0 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `e32a937be9`: target box: Cd 0.02811 > cd_max 0.025 |
| optuna | 99 | eval_budget | 40 | 0 | 8 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `b6cb0c9406`: NeuralFoil stall screen: d|Cl|/dalpha 0.026/deg < 0.055 |
| optuna | 110 | eval_budget | 40 | 0 | 7 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `80c926e40e`: NeuralFoil stall screen: d|Cl|/dalpha 0.021/deg < 0.055 |
| optuna | 121 | eval_budget | 40 | 0 | 3 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `d14681a693`: NeuralFoil stall screen: d|Cl|/dalpha 0.040/deg < 0.055 |
| optuna | 132 | eval_budget | 40 | 0 | 3 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `e656263f58`: NeuralFoil stall screen: d|Cl|/dalpha 0.038/deg < 0.055 |
| optuna | 143 | eval_budget | 40 | 0 | 2 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `8c90aaf0b9`: NeuralFoil stall screen: d|Cl|/dalpha 0.033/deg < 0.055 |
| optuna | 154 | target_met | 24 | 1 | 0 | 0 | 0 | 0 | $0.00 | 0.1 min | PASS `e9b5077ad5` |
| optuna | 165 | eval_budget | 40 | 0 | 3 | 0 | 0 | 0 | $0.00 | 0.1 min | closest `10df936f97`: NeuralFoil stall screen: d|Cl|/dalpha 0.036/deg < 0.055 |

## Methods

- **llm**: the agent graph with the real LLM (`--llm anthropic`, the client's default model,
  meta.json `llm_client`). Its runs were executed concurrently (one process per seed), so their
  wall clock includes some CPU contention between XFoil solves.
- **mock**: the same graph with `MockClient`, a deterministic rule-based stand-in (NOT an LLM):
  damped least-norm steps on the NeuralFoil sensitivities, promote the best promotable design.
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
- Graph runs (llm, mock): a declared plateau ends the run only after 80% of the budget; earlier
  it triggers exploration (wider trust region, or a restart from a different ledger region).

## Starts

| seed | camber | position | thickness | alpha |
|---|---|---|---|---|
| 44 | 0.011 | 0.3032 | 0.1206 | 13.5069 |

## Observations (hand-written from the run files, session 10; `scripts/benchmark.py report` keeps this section)

- **The LLM arm is incomplete: the Anthropic API credit ran out** ("credit balance is too low") 24 min
  into the batch. 1 of 15 seeds finished (seed 44: target met at 19 evaluations, $1.22, `7d78d095ac`
  m 0.09, p 0.353, t 0.1365, α 8.16, XFoil Cl −1.8143, Cd 0.02226, margin 0.078). Five runs were aborted mid-run as
  `invalid_llm` and nine at their first call; none of these 14 is counted above (an invalid real-LLM
  run is not a result). Their files are in `runs/bench2_aborted/`. The LLM row's interval (21–100%) is
  for n = 1 and says nothing yet.
- **Aborted LLM runs, censored** (evaluations completed with the LLM before the first credit error; no
  target met by then, so each is "not met within that many"):

  | seed | evals | est. cost | XFoil evals | closest design at abort |
  |---|---|---|---|---|
  | 11 | 24 | $2.00 | 5 | `df89b04bd3`: XFoil Cl −1.7943 (0.036 from the target) |
  | 22 | 25 | $2.05 | 1 | `24337fbf15`: TE separation (x/c 0.99) |
  | 33 | 28 | $2.07 | 6 | `5512db8397`: stall margin 0.022/deg |
  | 55 | 26 | $2.03 | 6 | `4feec6a30e`: stall margin 0.019/deg |
  | 66 | 14 | $0.91 | 3 | `b28bf79099`: XFoil Cl −1.7903 (0.040 from the target) |

  Like-for-like on the evaluations they did use: success within 19 evaluations, LLM 1 of the 5 runs that
  got that far; Optuna 0/15, random 0/15, mock 0/15. Within 25: Optuna 1/15 (seed 154, 24 evals).
  That is not a success rate; it needs the full 40-evaluation runs.
- **Optuna TPE 2/15 (13%, 95% 4–38%)**, at 24 and 33 evaluations, one XFoil evaluation each:
  `e9b5077ad5` (seed 154: m 0.0867, p 0.307, t 0.1335, α 8.86, Cl −1.8246, Cd 0.02433, margin 0.078) and
  `dac398b9df` (seed 33: m 0.0881, p 0.343, t 0.1315, α 8.20, Cl −1.8022, Cd 0.02213, margin 0.083).
  Both near the region of the gated sweep's box and live run 2's winner. Three XFoil evaluations in 15
  runs (seed 77's: Cl −1.8067 in the box, Cd 0.02578 over the cap).
- **Random search 0/15** never promoted (0 XFoil evaluations): uniform samples rarely land in the
  promotion window (5 near-target designs in 600 samples, all screen-failed); closest |ΔCl| 0.031.
- **Mock 0/15**, 0 XFoil evaluations: its alpha-led steps hover in the stall region (0–26 near-target
  designs per run, every one screen-failed); the mock never uses screen_override. With the plateau rule,
  13 runs end on a plateau at 32–39 evaluations (allowed from 32) after 0–18 deferred plateaus
  (widen / restart); 2 ran to the budget (seed 11 after 20 deferrals).
- **The Chief used screen_override on 24 of the 26 promotions to XFoil in the six LLM runs, and none of
  the 24 passed.** 15 failed on what the screen flagged (TE separation in the probe range or stall
  margin); 9 came back from XFoil less loaded than NeuralFoil (Cl −1.73 to −1.80), outside the box,
  so XFoil's stall gate never ran on them. Both screen-passed promotions were in seed 44; one is the
  winner. The overrides cost about 4 XFoil evaluations per run and found nothing; every logged reason
  argues the shortfall is marginal or that the screen over-flags. Several cite earlier overridden designs
  that "converged cleanly" at XFoil as evidence, but those had failed the target box, so XFoil's stall
  probe never ran on them; a few misstate the screen's numbers (slope sign, threshold).
- **No run stopped on a safety cap**; the most expensive LLM run reached $2.07 at 28 evaluations
  (about $0.075 per evaluation, so ~$3 for a full 40-evaluation run, under the $4 cap).
- No LLM run declared a plateau before it ended, so the plateau rule was not exercised by the LLM here.
- One sample per seed; the LLM is not deterministic. LLM wall clock includes five concurrent runs.

### Previous benchmark (v1, session 9, 5 seeds, `runs/bench/`)
LLM 1/5 (seed 44, 17 evals, $1.10), mock 0/5, random 0/5, 1 XFoil evaluation in 25 runs. Screen then
slope ≥ 0.0575 / TE H < 3.85 (43% of feasible window designs blocked); 4 of 5 LLM runs and all mock
runs declared a plateau with budget left.
