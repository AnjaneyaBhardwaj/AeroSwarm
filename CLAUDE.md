# aero-swarm

Multi-agent LLM system that optimizes a race-car wing section (later a diffuser)
against Cl/Cd targets. Full design: docs/BLUEPRINT.md. Read the relevant section
before working on any part.

## Non-negotiable architecture rules
- LLMs reason; deterministic code executes. Agents only emit Pydantic schemas
  (StrategyMemo, ParamDelta, RecoveryAction, Verdict). No agent writes shell
  commands or geometry code.
- State is the single source of truth. Agents never read each other's prose.
- Numbers in reports come only from the ledger, never from agent text.
- All LLM calls go through one client wrapper so tests can swap in a mock.

## Working rules
- Build one milestone at a time (BLUEPRINT.md "Suggested build order").
- Every module gets pytest tests. Tests must run without an API key or
  network: use the mock LLM and cached solver results.
- Python 3.11+, uv for dependencies, ruff for lint.
- Update docs/PROGRESS.md at the end of each session: what's done,
  what's next, known issues.
