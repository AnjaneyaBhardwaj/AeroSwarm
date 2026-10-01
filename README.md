# AeroSwarm

Multi-agent LLM system that optimizes a race-car wing section against Cl/Cd
targets. LLM agents (Chief, CAD, Critic) emit typed Pydantic schemas;
deterministic code builds geometry, runs NeuralFoil/XFoil and validates.
Design: [docs/BLUEPRINT.md](docs/BLUEPRINT.md). Status: [docs/PROGRESS.md](docs/PROGRESS.md).

```bash
make install   # uv sync
make xfoil     # build headless-safe XFoil 6.99 (the apt package aborts with SIGFPE)
make test      # offline; XFoil-binary tests skip if it is missing
make demo      # smoke test: real LLM if AEROSWARM_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY) is set, else the labelled mock (NOT an LLM)
make demo-hard # mock, 85% of attached Cl,max at Re 3e5: the NeuralFoil screen blocks every near-stall promotion
```

Live runs: cap them. `python -m swarm.run --llm anthropic --max-evals 10 --budget-usd 2`
stops cleanly (termination `cost_cap`) once the estimated LLM spend reaches the cap;
calls whose model has no entry in `PRICES` count as over the cap.
`--llm anthropic` needs `AEROSWARM_ANTHROPIC_API_KEY` (or the SDK's `ANTHROPIC_API_KEY`) and fails at startup without either. A real-LLM run with more
than 2 failed LLM calls is aborted, and one in which any agent never got a successful call is invalid
(termination `invalid_llm`, exit code 3, `require_real_llm()` refuses it). `report.md` and `meta.json`
show per-agent ok / failed / fallback counts.

Each run writes `runs/<id>/`: `ledger.jsonl`, `events.jsonl`, `traces.jsonl`
(tokens + estimated cost), `report.md`, `evolution_strip.png`, `evolution_morph.gif`,
`stall_<cid>.png` for each XFoil stall-margin probe, and `ckpt.db` (resume with
`python -m swarm.run --resume <id>`). `report.md` names the best *passing* design (a full
XFoil PASS) or says there is none, and then shows the closest candidate with its failing
checks; it never calls a TARGET_MISS "best". Termination is one of `target_met`,
`eval_budget`, `wall_clock`, `cost_cap`, `plateau`, `fatal`, `invalid_llm`.

Before a NeuralFoil candidate is promoted to XFoil it must pass the NeuralFoil screen:
d|Cl|/dα ≥ 0.05/deg over α+1 and α+2, and suction-side shape factor H < 4.25 at the TE
(calibrated on the Re 3e5 XFoil sweep: `scripts/clmax_sweep.py` then
`scripts/calibrate_screen.py`). XFoil's own gates stay authoritative; where the two disagree
on the same geometry, `events.jsonl` gets a `screen_xfoil_disagreement` event.

Limits: 2D sections only (no endplates, tip vortices or induced drag);
validator thresholds are project conventions to calibrate, not published limits.
