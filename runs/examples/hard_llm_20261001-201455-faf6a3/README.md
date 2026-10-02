# Example run: hard preset, real LLM, target met

```
python -m swarm.run --llm anthropic --preset hard --max-evals 40 --budget-usd 2
```

Run `20261001-201455-faf6a3`, code at commit `f05dc0c` (session 8), model `claude-sonnet-5`.
Target Cl −1.83 ± 0.03, Cd ≤ 0.025, Re 3e5, start m 0.06 / p 0.40 / t 0.10 / α 8.0.

**Result: target_met at generation 22** after 23 of 40 evaluations, 69 LLM calls (0 failed,
0 fallbacks), estimated cost $1.47, 0.28 h. Passing design `abb9803ead`: m 0.09, p 0.36, t 0.13,
α 8.349, XFoil Cl −1.8526, Cd 0.02222, stall margin 0.068/deg, no TE separation at α+0..+2.
The per-generation table and analysis are in `docs/PROGRESS.md` (session 8).

| file | what |
|---|---|
| `report.md` | the run's report as written at the end of the run |
| `evolution_strip.png`, `evolution_morph.gif` | before / most instructive failure / after, and the morph |
| `stall_<cid>.png` | XFoil stall-margin probe of each XFoil candidate (re-rendered with the session-9 label placement; data unchanged) |
| `ledger.jsonl` | every evaluation (the only source of numbers in the report) |
| `events.jsonl` | node events: strategies, CAD proposals, rejections, disagreements, screen/XFoil comparisons |
| `traces.jsonl` | every LLM call: prompt, structured output, tokens, estimated cost |
| `meta.json` | spec, start, client, termination, limits |

Checkpoints and per-candidate solver directories are not included.

## Changes made after this run (session 9)

- **NeuralFoil screen recalibrated** (slope ≥ 0.0575 and suction-side TE H < 3.85 at α+1/+2, was
  slope ≥ 0.05). Replayed on this run's four promotions it blocks the three XFoil rejected (gens 8,
  12, 15) **and also the passing design** (gen 22: H 4.12 at α+2 although XFoil shows no separation
  there). The calibration accepts that trade: ≤ 5% of screen passes fail XFoil, at the price of
  blocking ~43% of XFoil-feasible designs near the target. Under the new screen this run would not
  have promoted its winner.
- Near-duplicate guard (gens 9–11 here would be rejected) and the Chief/CAD deadlock rule.
