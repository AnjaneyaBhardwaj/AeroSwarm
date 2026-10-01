# Progress

## Session 5 (2026-10-01): first live LLM run (hard preset) — no design passes the stall gate

No code changed. `python -m swarm.run --llm anthropic --preset hard --max-evals 15 --budget-usd 2`
with `AEROSWARM_ANTHROPIC_API_KEY` set, real XFoil, run `20261001-023609-a2c08c`
(`runs/` is gitignored, so the table below is the record). Exit 0, `llm_valid: true`, termination
`budget` (15/15 evals; cost was far under the cap), model `anthropic:claude-sonnet-5`.
Spec: Cl −1.78 ± 0.03, Cd ≤ 0.02, Re 3e5; start camber 0.06 / p 0.4 / t 0.10 / alpha 8.0.

### Result: no target_met
- 40 LLM calls (chief 15, cad 10, critic 15), 0 failed, 0 fallbacks; 113,441 tokens in / 47,456 out,
  **estimated** cost $0.7014 (the run's own estimate, not a billing figure).
- **Best overall = best at XFoil = `01ee6bd07c`** (gen 7): Cl −1.7777, Cd 0.01973, camber 0.078, p 0.4,
  t 0.117, alpha 9.031. It is in the box but its stall slope is 0.026 (< 0.05), so the ledger status is
  TARGET_MISS (`EARLY_STALL`). `report.md` calls it "Best overall" without showing that status.
- Every XFoil result missed. Stall slope was measured for the in-box ones; all are under the 0.05 gate.

| gen | solver | Cl | Cd | camber | t | alpha | outcome |
|---|---|---|---|---|---|---|---|
| 0 | neuralfoil | −1.5392 | 0.01585 | 0.060 | 0.100 | 8.000 | miss (loading) |
| 1 | neuralfoil | −1.7308 | 0.02113 | 0.073 | 0.100 | 9.631 | miss (drag) |
| 2 | neuralfoil | −1.7443 | 0.02002 | 0.071 | 0.110 | 9.631 | miss (drag) |
| 3 | neuralfoil | −1.7556 | 0.02040 | 0.071 | 0.125 | 9.631 | miss (drag) |
| 4 | neuralfoil | −1.7576 | 0.01935 | 0.074 | 0.117 | 9.031 | PASS (not terminal) |
| 5 | xfoil | −1.7462 | 0.01929 | 0.074 | 0.117 | 9.031 | miss (loading, just outside the box) |
| 6 | neuralfoil | −1.7915 | 0.01982 | 0.078 | 0.117 | 9.031 | PASS (not terminal) |
| 7 | xfoil | −1.7777 | 0.01973 | 0.078 | 0.117 | 9.031 | miss: stall slope 0.026 |
| 8 | neuralfoil | −1.7929 | 0.02040 | 0.082 | 0.117 | 8.531 | miss (drag) |
| 9 | neuralfoil | −1.7933 | 0.01969 | 0.078 | 0.112 | 9.075 | PASS (not terminal) |
| 10 | xfoil | −1.7776 | 0.01963 | 0.078 | 0.112 | 9.075 | miss: stall slope 0.015 |
| 11 | neuralfoil | −1.7891 | 0.01946 | 0.081 | 0.117 | 8.531 | PASS (not terminal) |
| 12 | xfoil | −1.7961 | 0.01934 | 0.081 | 0.117 | 8.531 | miss: stall slope 0.031 |
| 13 | xfoil | −1.8105 | 0.01979 | 0.081 | 0.125 | 8.531 | miss (Cl 0.0005 past the box) |
| 14 | xfoil | −1.7506 | 0.01887 | 0.077 | 0.117 | 8.551 | miss: stall slope 0.036 |

### What the live LLM did differently from the mock
- It went camber-led: camber 0.060 → 0.081 and alpha 9.6° → 8.5° after the first stall rejection, with
  its hypotheses citing the sensitivities (e.g. dCl/dcamber ≈ −11.6). The mock's greedy steps reach Cl
  through alpha. This is the direction session 3 said the open question was about.
- It did not get far enough. The free set for `wing_1el` is only camber, camber_pos, thickness and
  alpha (`SINGLE_ELEMENT_PARAMS`). camber_pos stayed 0.4 in 14 of 15 designs (gen 8 tried 0.368, then
  went back), thickness stayed 0.10–0.125, and camber topped out at 0.082. The sweep in session 3 says
  attached designs exist at higher camber and a more aft camber position (m 0.09, p 0.5, alpha ~6.5:
  Cl −1.78, Cd 0.016); 15 evals from this start did not reach that region.
- NeuralFoil passed four designs (gens 4, 6, 9, 11); XFoil rejected all four when promoted
  (4 → 5 just outside the box on loading; 6 → 7, 9 → 10, 11 → 12 on stall slope). NeuralFoil is
  optimistic near the stall knee, which is the reason the gate exists.

### Known issues found by this run
- **The chief is not told why an XFoil candidate failed.** `chief_brief` (`swarm/briefs.py`) tables only
  gen/cid/fidelity/status/Cl/Cd/objective, ranks "Best 5" by objective, and passes only the latest
  verdict. The stall slope is not in any table. Result: `01ee6bd07c` sits at the top of "Best 5"
  with status TARGET_MISS and no reason. In the gen 9, 12 and 14 strategies the chief hypothesised a
  "marginal threshold / fallback flag" or "tolerance edge-case"; gen 14 even says the critic confirms
  no separation. The critic's verdicts for those designs were EARLY_STALL (gens 7, 10, 12). Gens 8, 11
  and 13 did name the stall knee, so it is not consistent. This is read from the code and the traces;
  I have not tested that adding the slope to the brief fixes it.
- `report.md` "Best overall" and "Best at XFoil" show Cl/Cd/objective but not the status, so a
  stall-rejected design reads like a winner. `best_record` ranks by objective regardless of status.

### Next
- Put the stall-probe result (slope, threshold, first separated alpha) and the failed-check names in
  the chief's brief and the Failure table, then rerun the same command. Expect cost ≈ $0.70 again.
- Show status (and the failed check) next to "Best overall" in `report.md`.
- Decide whether the hard demo should be able to finish (carried over from session 3): a start with
  more camber / aft camber_pos, or keep it as a rejection demo. This run is evidence it does not
  finish from the current start in 15 evals, with one run and one model.
- One run is one sample; the LLM is not deterministic. Repeat before drawing conclusions about the
  agents versus the mock.
- Milestone 2 is still not started (failure zoo, recovery metrics, sign-prediction scoring).

## Session 4 (2026-10-01): API key env var renamed, old name kept as a fallback

- The key is read from `AEROSWARM_ANTHROPIC_API_KEY` first, then `ANTHROPIC_API_KEY`; an empty value
  counts as unset (`resolve_api_key()` in `swarm/llm/client.py`). `AnthropicClient` passes the result to
  `anthropic.Anthropic(api_key=...)` explicitly, and raises `MissingAPIKey` (a `RuntimeError`) naming both
  variables when neither is set. A blank (whitespace-only) value also counts as unset. `make_client("auto")` uses the same helper, so it picks the real client exactly when
  `AnthropicClient` would accept a key. Before, the SDK silently read `ANTHROPIC_API_KEY` itself.
- CI blanks both variables so the suite stays keyless.
- `tests/test_llm.py` covers: mock with no key, new name, new name beating the fallback, fallback alone,
  empty new name falling back, and both empty (mock, plus the missing-key error).
- That session's known issue (`test_anthropic_client_logs_tokens_and_cost` failing when `AEROSWARM_MODEL`
  is exported) is fixed: the test clears the variable itself. See the LLM-run validity guard under Session 3.

## Session 3 (2026-10-01): near-stall PASS fix, before the first live run

Session 2's hard demo ended on `3df51198b3`, a PASS at Cl −1.976 / Cd 0.0287 with
suction-side Cf < 0 from x/c 0.91 to the TE. That design is now rejected (regression test).

### Done
- **TE separation can never be target_met.** New numeric check `te_separation`
  (severity `suspect`, any fidelity): suction-side Cf < 0 persisting to the TE makes the
  status TARGET_MISS and the result non-terminal, even inside the target box and even with a
  good stall margin. The diagnosis is `TE_SEPARATION_MAIN` (`EARLY_STALL` if it starts before
  x/c 0.5, unchanged); `review()` overwrites an LLM diagnosis that says otherwise with the
  deterministic one. Reattaching bubbles are still not TE separation.
- **Stall-margin check before target_met** (`swarm/critic/stall.py`).
  - A candidate that clears every other check at a terminal fidelity (XFoil, not a fallback,
    in the box, attached) is re-solved at alpha+1 and alpha+2 deg: same geometry, same
    fidelity, same ladder per probe (L0→L3, each level once). It runs in `numeric_validate`,
    so a non-candidate never pays for the two extra solves.
  - Margin = the smaller of the two forward secants of d|Cl|/dalpha (1/deg, downforce growth).
    `ValidatorConfig.stall_min_dcl_dalpha = 0.05` and `stall_probe_deg = (1, 2)`. This is a
    **project convention, not a published limit**: thin-airfoil slope is 0.110; in the sweep
    below, points with slope < 0.05 have a median 2.0° to the first TE-separated alpha and
    those at 0.08–0.10 have 4.8°. The relation is noisy, so 0.05 is a round number between
    "flattening" and "healthy", not a fit. Calibrate it when there are more validation cases.
  - A probe that cannot be solved (ladder exhausted, NaN) gives no margin and blocks target_met.
    `validate()` also blocks a terminal result when no probe was supplied.
  - Logged: `EvalRecord.stall_margin` (`StallMargin`: alphas, Cl, ladder level, TE separation
    at each probe, slopes, `dcl_dalpha`, threshold, ok, failure) in `ledger.jsonl`, a
    `stall_margin` event, and a column in `report.md`. Rows that never reached the probe
    (not in the box, separated, NeuralFoil) have `stall_margin = null`.
  - `xfoil.evaluate(..., alpha_deg=)` re-solves at another alpha in its own work dir.
- **Hard preset retuned** (`swarm/run.py`). Sweep: `scripts/clmax_sweep.py`, XFoil 6.99 at
  Re 3.0e5, ncrit 9, the wrapper's own ladder. Grid over the *feasible* single-element box:
  camber {0.06, 0.075, 0.09}, position {0.2, 0.3, 0.4, 0.5}, thickness {0.0955, 0.12, 0.15, 0.18},
  alpha 4–14° in 0.5° steps = 1008 points, all converged (998 at L0).
  - Thickness starts at 0.0955 because the FS2026 LE-radius rule rejects anything thinner in
    `build()`. My first sweep used t = 0.08 and gave a wrong "attached Cl_max 2.03"; discarded.
  - **Attached Cl_max = 2.092** (m 0.09, p 0.3, t 0.12, alpha 12.0, Cd 0.0312; TE separates at
    alpha 12.5). Next best 2.03 (m 0.09, p 0.2, t 0.0955). Highest Cl of any converged point,
    separated or not: 2.148. "Attached" = unbroken alpha run from 4° with no Cf < 0 to the TE.
    The grid is coarse (camber 0.015, position 0.1), so 2.092 is a lower bound on the true max.
  - **New target: Cl −1.78 ± 0.03 (85% of 2.092), Cd ≤ 0.020** (was −2.00, Cd ≤ 0.030).
    Attached designs in the Cl box have Cd 0.015–0.019; 0.020 leaves about 5% over the worst.
    Start point unchanged (m 0.06, p 0.40, t 0.10, alpha 8°).
- **Regression** (`tests/test_stall_margin.py`): `3df51198b3` is m 0.09, p 0.3709, t 0.1085,
  alpha 11.6191 (the 4-decimal values PROGRESS.md rounded away; checked against the cid).
  Under the old spec, real XFoil gives L0 not converged, L1 Cl −1.9758, Cd 0.02869, TE
  separation from x/c 0.912: in the box, now TARGET_MISS / TE_SEPARATION_MAIN, not terminal.
  There is an offline copy using the recorded numbers, so CI covers it. A second real-XFoil
  test: an in-box, attached design that separates one degree later and whose Cl peaks before
  alpha+2 (slope −0.029) is rejected by the probe.
- 147 tests at this point: 141 offline + 6 needing the XFoil binary (166 / 160 / 6 after the guard below).

### LLM-run validity guard (added later in session 3, before the first live run)
Why: with no API key, `--llm anthropic` ran all 15 evaluations on the deterministic fallbacks
(every call raised an auth error), exited 0 and wrote `is_mock: false`, 0 calls, $0.00. That run
looked like a live run and was meaningless. It is deleted.
- **Startup:** `--llm anthropic` (or `AEROSWARM_LLM=anthropic`) without a non-blank key
  (`AEROSWARM_ANTHROPIC_API_KEY`, else `ANTHROPIC_API_KEY`, via PR 4's `resolve_api_key()`) is a CLI error (exit 2) before any run directory exists. `run()`,
  `make_client()` and `AnthropicClient()` raise `MissingAPIKey` too. `--llm auto` without a key
  is still the labelled mock.
- **Counts per agent** (`LLMHealth` on the `TraceLogger`; chief / cad / critic):
  `ok`, `failed` (the call raised, was refused or returned nothing) and `fallbacks` (the graph
  substituted a deterministic output: Chief reused strategy, CAD deterministic proposal, Critic
  numeric-only verdict). Logged to `traces.jsonl` (`llm_call` with `ok`, `llm_failure`,
  `llm_fallback`), reloaded on resume, written to `meta.json["llm_health"]` and to a
  "LLM calls by agent" table in `report.md`. A cost-cap "no LLM call" verdict is not a fallback.
- **Validity (real LLMs only):** more than 2 failed calls aborts the run at the next routing
  boundary with no further LLM call (termination `invalid_llm`); at the end, any agent with no
  successful call, including one never called, also makes it invalid. Banner in `report.md`,
  `llm_health.valid = false` with reasons in `meta.json`, CLI exit code 3. The mock is not enforced.
  - Strict by design: a run too short to reach the CAD agent (`--max-evals 1`, or a cap hit before
    its first call) is invalid with "cad: no successful call (never called)".
- **`require_real_llm()`** takes a client or a finished run (run dir, `meta.json`, or the dict).
  It raises `InvalidLLMRun` (a `ValueError`) for an invalid run, an unfinished one, or one without
  an `llm_health` record. It still rejects mocks.
- **Sonnet 5 priced:** `claude-sonnet-5` = $2 in / $10 out (5m cache write $2.50, cache hit $0.20),
  from https://platform.claude.com/docs/en/about-claude/pricing, fetched 2026-10-01 (URL and date are
  in the `PRICES` comment). Every existing row matched that page. Without it the cost cap treats
  every call as unpriced and stops after the first one. `AEROSWARM_MODEL=claude-sonnet-5` is kept
  as set in the environment.
- `tests/test_llm.py` clears `AEROSWARM_MODEL` itself (monkeypatch). New `tests/test_llm_guard.py`
  (19 tests): startup, per-agent counting and resume reload, the 2/3-failure boundary, agent never
  succeeding / never called, `require_real_llm` for every input form, CLI exit codes.
- Not changed: `--resume` of an invalid run reloads its failure counts, so it aborts again.

### What the hard demo does now (mock, this XFoil build) — it does NOT reach target_met
`make demo-hard`: 21 evals, termination `plateau`. NeuralFoil gens 0–2 climb to Cl −1.755, then
XFoil gens 3–4 are **TE-separated TARGET_MISS** (x/c 0.993; still the strip's middle frame).
From gen 5 the mock sits on in-box designs (Cl −1.77…−1.78, Cd 0.0195–0.0198) whose probes show
slope +0.03 then ≈ −0.03: each is TARGET_MISS with the margin logged. The mock's greedy
gradient steps reach Cl through alpha, not camber, so it never finds the attached, high-camber
designs the sweep says exist (m 0.09, p 0.5, alpha ~6.5 gives Cl −1.78 at Cd 0.016).
I tried Cd caps 0.016–0.018 and targets −1.70/−1.74 with the same start: none ended in target_met.
I did not lower the threshold to make the mock pass (its designs sit at 0.03–0.033).
- **The L0 → L1 recovery no longer happens in the hard demo**: every solve in the committed
  preset's run converged at L0 (an L1 solve showed up only in one experiment with a different target). Session 2's recovery came from
  designs deep in stall, which the gate now rejects. The ladder is still covered by fake-ladder
  tests; the hard-demo test dropped its recovery assertion and now checks the separation and
  no-margin gates and the PASS invariant (an XFoil PASS is attached and has a passing margin).
  Keeping the start point did not keep the recovery; a start/target that does both would need
  a different optimizer path.

### Side effect on the default demo (changed, please check)
With the gate the default `make demo` (Cl −1.50, Cd ≤ 0.018, Re 8.3e5) also ended in `plateau`:
its low-camber start (m 0.02) reaches −1.5 at alpha ≈ 9.5° with slope 0.042–0.047. I moved
`DEMO_START` and the test `start` fixture to camber 0.06; with real XFoil it now reaches
target_met in 4 evaluations (m 0.07 also works, m 0.05 plateaus). The spec is untouched.

### Known issues / limits
- `te_separation` follows the existing definition (≥ 2 stations to the TE). A single
  reversed TE station (`cf_te < 0` only) is not flagged.
- The probe adds two XFoil solves (plus ladder retries) for each would-be-final candidate.
  A NeuralFoil-only fallback result can never pass, so it is not probed.
- Everything in session 2's list still holds (no live API call yet; costs are estimates).

### Next
- No live run yet (no key in this environment; it will be added in a new session). First live run:
  `python -m swarm.run --llm anthropic --preset hard --max-evals 15 --budget-usd 2`. Expect a real
  LLM to take its own path; whether it finds a camber-led design is the open question.
- Decide whether the hard demo should be able to finish (e.g. a start with more camber) or
  stay a rejection demo.
- Milestone 2 (not started): failure zoo for the XFoil ladder, recovery-rate metrics,
  sign-prediction scoring.

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
    empty `AEROSWARM_ANTHROPIC_API_KEY`. No XFoil in CI; the 4 binary tests are deselected.
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
- First live run with `AEROSWARM_ANTHROPIC_API_KEY`; compare its traces with the mock's.
