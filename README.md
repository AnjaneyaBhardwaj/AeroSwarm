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
make demo-hard # mock, hard target Cl -1.83 ± 0.03, Cd <= 0.025 at Re 3e5 (near the gated Cl,max)
```

Rules: the section is checked against the **Formula SAE Rules 2027 v1.0**
([docs/FSAE_Rules_2027_V1.pdf](docs/FSAE_Rules_2027_V1.pdf)), on outlines placed on a placeholder
car (`PLACEHOLDER_CAR`, not a real car): T.7.7.1 height (≤ 1200 mm in the Rear Aerodynamic Zone,
≤ 500 mm outside it), T.7.5b (≤ 250 mm behind the rear tires), T.7.1.4 (5 mm radius on forward
facing horizontal edges, so NACA thickness ≥ 0.123 on the 300 mm chord), T.7.1.5 (edges not sharp:
the trailing edge is kept ≥ 2 mm thick) and V.1.4.1 (no ground contact). Width (T.7.6) and end
plates need the 3D stage. `DesignSpec.rulebook = "FS2026_v1.1"` selects Formula Student 2026.

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
d|Cl|/dα ≥ 0.055/deg and suction-side TE shape factor H < 4.35 at α+1 and α+2, and H < 4.25 at α
(cost-weighted calibration on the gated Re 3e5 XFoil sweep: `scripts/calibrate_screen_rules.py`).
The Chief may overrule the screen with a logged `screen_override` reason, at most twice per run and
only for a design whose NeuralFoil result is inside the target box; every brief shows its override
record. XFoil's own gates stay authoritative; an XFoil result whose stall probe did not run is
labelled `stall_untested` and is not counted as evidence about the screen.

Limits: 2D sections only (no endplates, tip vortices or induced drag);
validator thresholds are project conventions to calibrate, not published limits.
