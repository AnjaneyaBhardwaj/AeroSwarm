# Aeroptimize run viewer

Static page (no build step) that replays exported runs. Data: `runs/*.json`, written by
`scripts/export_run.py`; `runs/index.json` lists them.

```bash
uv run python scripts/export_run.py runs/<run_dir> [--name NAME] [--optuna auto|none|<optuna_run_dir>]
make viewer   # http://localhost:8000
```

URL options: `?run=<name>&gen=<n>&autoplay=0&speed=4`. Keys: space play/pause, ←/→ step.
Every number shown comes from the run ledger; agent text is verbatim from `traces.jsonl` (long text is
cut, never rewritten); section outlines are precomputed by the exporter.

## Live mode (local only)

```bash
make live     # http://127.0.0.1:8000: the same page, plus a "Live run" panel
```

`swarm/live.py` serves this directory and starts a real swarm run (hard preset, `swarm.run.run`) from the dial
values, streaming each generation over Server-Sent Events as the same record a recorded export holds. The page
shows the panel only when `api/health` answers, so a static copy of the page stays replay-only and can never
spend an API key. Before a run, the dials are checked against the run's own geometry and rulebook checks.

- Agents: Claude (needs `AEROSWARM_ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY` on the server) or the mock
  (free, rule-based, labelled NOT an LLM).
- Caps per run: evaluations (default 15, max 40), estimated LLM cost (default $1, max $5; the run stops with
  termination `cost_cap`), 30 minutes wall clock, one run at a time. The page shows the estimate before the
  run starts and the spend while it runs. Default model `claude-sonnet-5-5`, hybrid (Optuna inner loop) on.
- While a run goes, a line above the feed says what is happening now (which agent or solver is working); Stop
  ends it at the next step boundary with termination `stopped` (it is still saved).
- A finished run is saved to `runs/live/<id>/` and exported, with its Optuna comparison, to
  `viewer/runs/live/` (git-ignored); it joins the gallery through the server's merged `runs/index.json`. To
  publish one, export it into `viewer/runs/` with `scripts/export_run.py runs/live/<id>`.

To put the viewer and live runs on your own website (access code, daily spend cap, Docker image, reverse
proxy settings), see [docs/DEPLOY.md](../docs/DEPLOY.md).
