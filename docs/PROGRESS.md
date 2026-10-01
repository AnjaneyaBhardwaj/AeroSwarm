# Progress

## Session 2 (2026-10-01): pre-milestone-2 hardening

### Done
- **Non-finite guard.** Our XFoil build has FP traps off, so a blown-up solve can
  print `NaN`, `Infinity` or Fortran `****` instead of aborting.
  - `parse_polar` drops any row with a non-finite value (`finite_only=False` returns
    the raw rows); `parse_dump` raises `NonFiniteDump` on NaN/inf surface x or Cf.
  - The wrapper labels these `nonfinite_coeffs@L<k>` / `nonfinite_cf@L<k>` (status
    `not_converged`), so the ladder moves to the next level.
  - The numeric Critic has a new `finite` check, run right after convergence. It covers
    Cl, Cd, Cm, and the Cf-derived BL facts: the new `BoundaryLayerSummary.cf_te`
    (suction-side Cf at the TE), separation and transition x/c, and bubble extents.
    A failure is NUMERICAL_FAILURE (→ `cfd_recover`), not NON_PHYSICAL, and no
    later check runs on the bad values. `usable()`, `objective()`, the fidelity-gap
    check and `suggest_diagnosis` also ignore non-finite rows.
  - `tests/test_nonfinite.py` (33 tests), including a graph run where L0 returns NaN
    and the run recovers at L1.
- **`make demo-hard`** (`--preset hard`, mock pinned): target Cl −2.00 ± 0.03,
  Cd ≤ 0.030, Re 3e5 (15 m/s on 300 mm). Start: m 0.06, p 0.40, t 0.10, α 8°.
  The run is deterministic with the mock and this XFoil build. **What it actually did:**
  - gens 0–3, NeuralFoil: Cl −1.539 → −1.731 → −1.865 → −1.969. Gen 2 includes the
    injected bounds violation, which is rejected.
  - gen 4: promotes `596488f588` to XFoil. L0 fails (100 iterations, rms 0.51);
    `xfoil_recovery` L0 → L1, which converges at iteration 117. Result: Cl −1.944,
    Cd 0.0268, suction-side Cf < 0 from x/c 0.93 to the TE.
    **TARGET_MISS, TE_SEPARATION_MAIN.** This is the strip's middle frame.
  - gen 5: `3df51198b3` (m 0.09, p 0.371, t 0.1085, α 11.62°). L0 fails again and L1
    converges at iteration 142. Result: Cl −1.976, Cd 0.0287 → **PASS, target_met**
    after 6 evaluations.
  - The final design is still mildly TE-separated (x/c 0.91, Cf_TE ≈ −2.5e-5). It is
    in the target box, but it is a near-stall design, and the Critic's diagnosis says so.
  - `make demo` is unchanged and stays the smoke test.
  - `tests/test_demo_hard.py` checks the recovery, the separated TARGET_MISS round as
    the middle frame, and target_met. It needs the binary (marked `xfoil`).
- **CI** (`.github/workflows/ci.yml`): runs on every push and PR.
  - Lint job: `ruff check` + `ruff format --check`.
  - Test job: Python 3.11 and 3.12, `uv sync --locked`, `pytest -m "not xfoil"`,
    empty `ANTHROPIC_API_KEY`. No XFoil in CI; the 4 binary tests are deselected.
- **Live-run caps**
  - `--max-evals` now overrides whichever preset is selected (it was already there for
    the default spec).
  - New `--budget-usd` sets `DesignSpec.max_cost_usd`. The cap is checked at every
    routing boundary (after chief, CAD, geometry and critic). Once the estimated spend
    reaches the cap, no further LLM call is made. A candidate that is already proposed
    is still solved and recorded, with the numeric verdict and no Critic LLM call. The
    run then writes its report with termination **`cost_cap`** (event
    `cost_cap_reached`). Overshoot is at most the one call that crossed the cap.
  - A call priced as unknown (model not in `PRICES`) counts as over the cap.
  - A real-LLM run without a cap prints a warning.
  - `TraceLogger` reloads totals from an existing `traces.jsonl`, so a resumed run
    counts its earlier spend. `--resume` refuses `--preset/--max-evals/--budget-usd`,
    because the spec is fixed at run start. Previously, resume overwrote meta.json's
    spec with the demo spec; that is fixed.
  - Tests: `tests/test_budget.py`.
- 125 tests: 121 offline + 4 that need the XFoil binary.

### Known issues / limits
- Hard-demo determinism is for the mock + this XFoil 6.99 build + the pinned
  NeuralFoil. A different XFoil build/compiler may converge at L0 and skip the recovery;
  the `xfoil` test would catch that. A real LLM takes its own path.
- The hard demo hits L0 → L1 only. L2/L3 and fallback are still covered only by the fake ladder.
- Cost is an *estimate* from `PRICES` (hand-maintained, USD/MTok); it is not billing data.
- Still no live API call made (no key in this environment).

### Next
- Milestone 2 (not started): failure zoo for the XFoil ladder, recovery-rate metrics,
  sign-prediction scoring.
- First live run: `python -m swarm.run --llm anthropic --max-evals 10 --budget-usd 2`.

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
