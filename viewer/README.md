# Aeroptimize run viewer

Static page (no build step) that replays exported runs. Data: `runs/*.json`, written by
`scripts/export_run.py`; `runs/index.json` lists them.

```bash
uv run python scripts/export_run.py runs/<run_dir> [--name NAME] [--optuna auto|none|<optuna_run_dir>]
make viewer   # http://localhost:8000
```

The page reads top to bottom:

1. **Headline:** what the project is, the run's result (target met in N evaluations, or the closest design and
   what it fails), its final Cl and Cd against the target, and one "Watch the replay" button.
2. **Replay:** the wing and the Cl–Cd polar, the generation's one-sentence story, and play / step / scrub
   controls. Below it, one line per agent step (Chief, CAD, Optuna, solver, Critic, notable events), written by
   code from the export's fields; "Show reasoning" adds each agent's own words under its line.
3. **Details** (closed): start-design dials and the nearest recorded start, the live-run panel (local server
   only), target and run facts, the Optuna comparison and the CAD downloads.

The page opens on the last generation, paused. URL options: `?run=<name>&gen=<n>&autoplay=1&speed=4&intro=1`
(`autoplay=1` plays from the start, `intro=1` opens the "How to read this" dialog, otherwise behind the ?
button). Keys: space play/pause, ←/→ step.
Every number shown comes from the run ledger; agent text is verbatim from `traces.jsonl` (long text is
cut, never rewritten); section outlines are precomputed by the exporter.

## Live mode (local only)

```bash
make live     # http://127.0.0.1:8000: the same page, plus a "Live run" panel
```

`swarm/live.py` serves this directory and starts a real swarm run (hard preset, `swarm.run.run`) from the dial
values, streaming each generation over Server-Sent Events as the same record a recorded export holds. The page
shows the panel (in Details, with a "Start a live run" link under the headline) only when `api/health` answers,
so a static copy of the page stays replay-only and can never spend an API key. Before a run, the dials are checked against the run's own geometry and rulebook checks.

- Agents: Claude (needs `AEROSWARM_ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY` on the server) or the mock
  (free, rule-based, labelled NOT an LLM).
- Caps per run: evaluations (default 15, max 40), estimated LLM cost (default $1, max $5; the run stops with
  termination `cost_cap`), 30 minutes wall clock, one run at a time. The page shows the estimate before the
  run starts and the spend while it runs. Default model `claude-sonnet-5-5`, hybrid (Optuna inner loop) on.
- While a run goes, the headline shows its progress and a line above the wing says what is happening now
  (which agent or solver is working); its Stop button ends it at the next step boundary with termination
  `stopped` (it is still saved).
- A finished run is saved to `runs/live/<id>/` and exported, with its Optuna comparison, to
  `viewer/runs/live/` (git-ignored); it joins the gallery through the server's merged `runs/index.json`. To
  publish one, export it into `viewer/runs/` with `scripts/export_run.py runs/live/<id>`.

To put the viewer and live runs on your own website (access code, daily spend cap, Docker image, reverse
proxy settings), see [docs/DEPLOY.md](../docs/DEPLOY.md).
