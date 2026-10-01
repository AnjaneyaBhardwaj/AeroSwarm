# Progress

## Session 1 (2026-10-01): milestone 1 — T0 + T1 graph, NACA 4-digit, numeric Critic

### Done
- **State** (`swarm/state.py`): §1 schemas. `DesignSpec.reynolds` is computed from
  `speed_mps` and `car.chord_mm` (ν = 1.5e-5, BLUEPRINT appendix); passing a
  mismatched `reynolds` is rejected. `ncrit` (default 9) is a spec field used by
  both XFoil and NeuralFoil. `WingParams` are quantized to 1e-4 on construction,
  so the cid names exactly the geometry evaluated. Slot bounds updated
  (gap ≤ 0.06, overlap ≤ 0.07).
- **Geometry** (`swarm/cad/`): `naca4()`, Selig `.dat` export, 2D validation
  (area, self-intersection, thickness, TE mesh floor), FS2026 checks on outlines
  scaled to mm and placed at the mount point (`placed_mm`). The LE-radius
  thickness floor is computed from r_LE = 1.1019 t² c (→ 0.0953 on 300 mm), and
  the TE-radius rule checks ≥ 2 mm TE thickness. `propose_delta` checks
  (unknown/not-allowed param, bounds, trust region, duplicate cid per fidelity)
  return `ToolError`s verbatim; deterministic fallback after 3 failed repairs.
- **Solvers**: NeuralFoil (`large`) with central-difference sensitivities;
  XFoil wrapper with a 4-level ladder (direct, 300 iterations, α continuation,
  continuation + 240 panels), then NeuralFoil fallback flagged
  `fallback_from="xfoil"`. TE separation = suction-side Cf < 0 that persists to
  the TE (≥ 2 stations); runs that reattach are recorded as laminar bubbles.
- **Numeric Critic** (`swarm/critic/numeric.py`): all thresholds in one
  `ValidatorConfig` (project conventions to calibrate, not published limits).
  Only a non-fallback XFoil result can be terminal (`target_met`).
  `merge_verdict` enforces in code that the LLM may downgrade, never upgrade.
- **LLM layer** (`swarm/llm/`): one `structured()` wrapper. `AnthropicClient`
  (claude-opus-5-5, `beta.messages.parse` with Pydantic output, adaptive
  thinking, server-side refusal fallback). `MockClient` is labelled
  "NOT an LLM" in code, `meta.json`, `traces.jsonl` and `report.md`;
  `require_real_llm()` rejects it for any comparison. Every call logs tokens,
  latency and estimated cost to `traces.jsonl`, with a `run_summary` line at the end.
- **Graph** (`swarm/graph.py`): LangGraph with SqliteSaver checkpoints
  (explicit msgpack allowlist for our types), `node_boundary`,
  `route_after_critic`, recursion_limit 1000 (explicit; LangGraph 1.x default is 10007).
- **Viz** (`swarm/viz/evolution.py`): before/middle/after strip PNG and parameter-space
  morph GIF; separation shading from XFoil Cf only.
- **XFoil install**: `scripts/install_xfoil.sh` builds 6.99 from the Ubuntu source
  package without FP traps. The stock `apt install xfoil` binary is compiled with
  `-ffpe-trap=invalid,zero` and aborts with SIGFPE mid-solve. SessionStart hook
  (`.claude/hooks/session-start.sh`) runs `uv sync` + the build in web sessions (~26 s cold).
- **Tests**: 77 tests (74 offline + 3 that need the real XFoil binary and skip without it),
  including a headless proof: graphics off with an unreachable `DISPLAY=:99`, plus a
  negative control showing XFoil aborts without `PLOP G`.
- `make demo`: mock run reaches target_met in 6 evaluations (NeuralFoil screening →
  promotion → XFoil PASS) and writes `runs/<id>/{ledger,events,traces}.jsonl`,
  `report.md`, `evolution_strip.png`, `evolution_morph.gif`.

### Deviations from the blueprint (deliberate)
- `StrategyMemo` gained `promote_cid` (re-evaluate a ledger candidate at a higher tier
  without a CAD step) and `declare_plateau`. `CFDResult` gained `confidence`,
  `solver_level`, `fallback_from`, `bl`, `artifacts`. `Verdict.findings` is typed (`Finding`).
- In M1, `cfd_recover` is deterministic (next untried ladder level). A
  NUMERICAL_FAILURE that reaches the Critic has exhausted the ladder, so it routes to
  the Chief (Scenario B step 4), not back to `cfd_recover`.
- The Critic LLM writes the diagnosis and findings; the status comes from the numeric
  report via `merge_verdict`.
- Only one ledger row per completed evaluation; individual failed ladder levels go to
  `events.jsonl`.

### Known issues / limits
- The real-LLM path has only been tested against a fake SDK; no live API call
  has been made yet (no key in this environment).
- The default mock demo is "easy": it never hits an XFoil convergence failure or TE
  separation, so the demo strip has no separation shading. Those paths are covered by
  unit/graph tests (recorded XFoil output, a fake ladder). The mock injects one labelled
  bounds violation in generation 2 to show the rejection path (`--no-faults` to disable).
- `scripts/install_xfoil.sh` needs apt + the Ubuntu archive; no macOS path yet.
- Placeholder `ReferenceCar` numbers are not a real car.
- CAD sign-prediction accuracy is recorded per row (`predicted_signs`) but not yet scored.
- HTML wing viewer (§5) not built yet.

### Next
- Milestone 2: failure zoo for the XFoil ladder (stall, high camber, thin sections),
  recovery-rate metrics, sign-prediction scoring.
- First live run with `ANTHROPIC_API_KEY`; compare its traces with the mock's.
