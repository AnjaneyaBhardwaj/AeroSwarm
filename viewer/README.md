# AeroSwarm run viewer

Static page (no build step) that replays exported runs. Data: `runs/*.json`, written by
`scripts/export_run.py`; `runs/index.json` lists them.

```bash
uv run python scripts/export_run.py runs/<run_dir> [--name NAME] [--optuna auto|none|<optuna_run_dir>]
make viewer   # http://localhost:8000
```

URL options: `?run=<name>&gen=<n>&autoplay=0&speed=4`. Keys: space play/pause, ←/→ step.
Every number shown comes from the run ledger; agent text is verbatim from `traces.jsonl` (long text is
cut, never rewritten); section outlines are precomputed by the exporter.
