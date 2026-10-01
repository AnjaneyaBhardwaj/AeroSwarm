# AeroSwarm

Multi-agent LLM system that optimizes a race-car wing section against Cl/Cd
targets. LLM agents (Chief, CAD, Critic) emit typed Pydantic schemas;
deterministic code builds geometry, runs NeuralFoil/XFoil and validates.
Design: [docs/BLUEPRINT.md](docs/BLUEPRINT.md). Status: [docs/PROGRESS.md](docs/PROGRESS.md).

```bash
make install   # uv sync
make xfoil     # build headless-safe XFoil 6.99 (the apt package aborts with SIGFPE)
make test      # offline; XFoil-binary tests skip if it is missing
make demo      # real LLM if ANTHROPIC_API_KEY is set, else the labelled mock (NOT an LLM)
```

Each run writes `runs/<id>/`: `ledger.jsonl`, `events.jsonl`, `traces.jsonl`
(tokens + estimated cost), `report.md`, `evolution_strip.png`, `evolution_morph.gif`,
and `ckpt.db` (resume with `python -m swarm.run --resume <id>`).

Limits: 2D sections only (no endplates, tip vortices or induced drag);
validator thresholds are project conventions to calibrate, not published limits.
