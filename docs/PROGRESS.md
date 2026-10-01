# Progress

## Session 8 (2026-10-01): hard target applied, gate aligned, search-loop fixes

### Hard target: Cl −1.83 ± 0.03, Cd ≤ 0.025 (`HARD_SPEC`)
- **Derivation rule** (`scripts/gated_sweep.py`, session 7's sweep: 10,045 XFoil points at Re 3e5,
  ncrit 9). A grid point passes the gate if it converges at alpha, +1, +2, has no TE separation at
  any of the three, keeps d|Cl|/dalpha ≥ 0.05/deg over alpha..alpha+2, and clears the FS2026 geometry
  checks. With the Cd cap fixed at 0.025, the target is the hardest |Cl| (0.01 steps, tol ±0.03 kept)
  whose box holds ≥ 10 passing points away from the binding bounds (camber < 0.09, thickness > 0.0955).
  Chosen by the user over −1.89 / Cd 0.0325 (session 7) to keep the drag cap meaningful.
- **Region size**: 28 passing grid points in the box (p 0.25–0.55 grid; the p 0.20 slice adds none):
  13 interior (m 0.075–0.085, p 0.25–0.35, t 0.11–0.135, alpha 8.5–9.75) and 15 on the camber bound
  (m 0.09). Cold through the real pipeline (ladder, screen, probe, validator): **27/28 pass — 12/13
  interior, 15/15 on the bound.** The failure (m 0.085 p 0.25 t 0.11 α 9.75) converges cold to a
  different XFoil solution (Cl −1.8615, Cd 0.0279 vs continuation's −1.8033 / 0.0199), outside the Cd cap.
- **Witness** (`tests/test_hard_target.py`): m 0.085, p 0.30, t 0.12, alpha 9.0. Cold: NeuralFoil
  screen ok (slope 0.063, TE H 3.07); XFoil L0 Cl −1.8261, Cd 0.02412, margin 0.070/deg, no separation
  at alpha+0..+2, validator PASS terminal. NeuralFoil reads Cl −1.806 (in the box, promotable).
  Its alpha (±0.25) and thickness (0.11, 0.135) neighbours pass and are in the box; its camber
  neighbours pass the gate but fall just outside the box (m 0.08: Cl −1.790; m 0.09: Cd 0.02505); in
  position, p 0.25 passes the gate with Cd 0.0266 (over the cap) and p 0.35 fails it (margin 0.009).
- **The camber bound (0.09) is active for the best gated designs**: gated Cl_max rises with camber
  (0.06 → 1.690 … 0.09 → 1.979) and the best is on the bound; 15 of the 28 box points sit on it. The
  target does not depend on it (12 interior points pass cold). Bound unchanged.
- **The target is XFoil-derived** (2D, panel + integral BL, ncrit 9, Re 3e5). Re-check the gated
  Cl_max, the box and the witness when the OpenFOAM tiers arrive; RANS will move the stall margin.
- The old box (−1.78 / 0.020) held 8 passing points, 4 on the camber bound.

### Gate aligned with the sweep
`measure_stall_margin`: TE separation at alpha+1 or alpha+2 now fails the margin (it was only
logged), so the pipeline's gate is the gate the target was derived with. `failing_checks` says
"TE separation within the probe range" when the slope passes but a probe separates.

### Search-loop fixes (last round's items 1–5; `tests/test_loop_fixes.py`)
1. **CAD diagnosis = base design.** `cad_brief` takes the diagnosis from the base's own
   (highest-fidelity) record, never the latest verdict; facts carry `base_cid` / `diagnosis_cid`.
   The graph test fails if they differ (checked by reverting the fix: both tests fail).
2. **Directional focus.** `StrategyMemo.focus_params` are `{name, direction: + | - | free}` (bare names
   still read as free). A CAD change against a direction is rejected (`ToolError` "direction") unless
   it carries `override_reason`; accepted overrides are logged as `chief_cad_disagreement`. The Chief
   brief lists its last 8 hypotheses with their ledger outcomes (cid, fidelity, status, Cl/Cd, first
   failing check), the next CAD base and why, and a "failing" column in its tables.
3. **Parent selection** (`ledger.select_parent`): the best design that passed all checks at its own
   fidelity, judged on each cid's highest-fidelity record (an XFoil rejection overrides a NeuralFoil
   pass); if none passed, the least constraint violation: stall-margin shortfall / threshold +
   separation (0/1) + distance outside the box / cl_tol (Cd at the objective's rate); objective only
   breaks ties. A `parent_selected` event records the cid and why.
4. **EARLY_STALL** from a failed XFoil stall margin, or (NeuralFoil results only) a failed screen,
   with the slopes, margin vs threshold and shortfall, and the first separated alpha as evidence. The
   Critic cannot relabel it (same rule as TE separation); an LLM EARLY_STALL keeps its wording and gets
   the numbers prepended.
5. **Direct-to-XFoil screening.** A fresh design (no `promote_cid`) sent to XFoil is screened in
   `geometry_build`; a failure evaluates it at NeuralFoil instead (`direct_xfoil_screened_out`), unless
   the Chief sets `screen_override` to a reason (`screen_override` event).
- Prompts updated (chief.md: directions, history, screen_override; cad.md: directions, override_reason).
- Tests 201 → 212.

### Known issues / limits
- A NeuralFoil result with low surrogate confidence still escalates to XFoil through `cfd_recover`
  without the screen (unchanged path).
- The mock hard demo is unchanged in outcome: its alpha-led path stays near Cl,max; 25 NeuralFoil
  evals, plateau, nothing promoted.

## Session 7 (2026-10-01): gated sweep, re-derived hard target (proposal; session 8 applied −1.83 instead)

### The session 3/5 "m 0.09, p 0.5, alpha ~6.5" claim was wrong
Session 3 wrote that the sweep has "attached, high-camber designs (m 0.09, p 0.5, alpha ~6.5 gives
Cl −1.78 at Cd 0.016)", and session 5 repeated it as evidence that passing designs exist. That point
is attached **at its design alpha only**; it has no stall margin. Through the real pipeline (cold
ladder, probe at alpha+1/+2): t 0.0955 → margin −0.003/deg, TE separation from x/c 0.98 at alpha+1;
t 0.12 → 0.026/deg, separated at alpha+1; alpha 6.0 → 0.010–0.016/deg. The claim predates the
stall-margin gate (session 3 checked attachment, not margin) and nobody re-checked it against the
gate. The NeuralFoil screen rejects all of them too. Only one point of the old 1008-point grid
(m 0.09, p 0.4, t 0.12, alpha 7.0) passed the full gate for Cl −1.78.

### Gated sweep (`scripts/gated_sweep.py`)
- Grid: camber 0.06–0.09 step 0.005, position 0.25–0.55 step 0.05, thickness {0.0955, 0.11, 0.12,
  0.135, 0.15}, alpha 4–14 step 0.25: 245 geometries, 10,045 points, Re 3e5, ncrit 9. One XFoil session
  per geometry with alpha continuation (warm-up from 0°, the wrapper's L2 settings); 265 points that
  failed in continuation were re-solved cold through the ladder; 0 failed. 11 min on 4 cores.
- Alpha range: the request was 4–10, but then a design can only be gated up to alpha 8 (alpha+2 ≤ 10)
  and every best gated design sat on that edge; 4–12 moved the edge to alpha 10 and the best still sat
  on it. 4–14 gates designs up to alpha 12; the best is now at 10.75. The three runs agree exactly on
  shared points (max |ΔCl| 0, no separation flips).
- Gate per point (user definition): converged at alpha, +1, +2; no TE separation at any of the three;
  stall margin ≥ 0.05/deg; FS2026 geometry checks. **3,115 points pass** (3,261 pass the pipeline's
  own gate, which only logs separation at the probes).
- **Gated Cl_max = 1.979** (m 0.09, p 0.25, t 0.11, alpha 10.75; Cd 0.0315, margin 0.060). Gated |Cl|
  range 1.057–1.979; 99th percentile 1.872.
- **Current box (Cl −1.78 ± 0.03, Cd ≤ 0.020): 8 passing points**, all at m ≥ 0.085, 4 of them at the
  camber bound.

### Proposed hard target (not applied; session 8 chose −1.83 / Cd 0.025 from the alternatives)
**Cl −1.89 ± 0.03, Cd ≤ 0.0325** (95.5% of gated Cl_max). Rule (`gated_sweep.py propose`): the highest
target, in 0.01 steps, whose ±0.03 band holds ≥ 10 passing points away from the binding bounds
(camber < 0.09, thickness > 0.0955 LE floor); Cd cap = worst Cd among those + 5%, rounded up to 0.0005.
- 31 passing grid points in the box: 12 interior, 19 on the camber bound (m 0.09; 3 of them also on
  the thickness floor). Positions 0.25–0.35, thickness 0.0955–0.135, alpha 9.0–11.0.
- Cold cross-check of all 31 through the real pipeline (build, NeuralFoil screen, XFoil ladder, stall
  probe, validator): all converge at L0 with the sweep's Cl, all in the box, attached, margin ≥ 0.05.
  **29/31 pass everything.** Two interior points drop out: m 0.08 p 0.25 t 0.12 α 10.75 (NeuralFoil
  screen slope 0.04995, blocked; XFoil margin 0.063) and m 0.085 p 0.3 t 0.135 α 10.25 (cold probe at
  α+2 separates at x/c 0.99; continuation did not). So **10 interior points pass the screen and the full
  gate cold**.
- **Witness: m 0.085, p 0.30, t 0.12, alpha 9.5** (cid 8c50a2f006), between grid neighbours on every
  axis. Real pipeline: NeuralFoil screen ok (slope 0.056, TE H 3.18); XFoil L0 Cl −1.8782, Cd 0.02505,
  attached; stall margin 0.072/deg, no separation at α+1/+2; validator PASS, terminal. At NeuralFoil
  it reads Cl −1.846 (0.044 short: TARGET_MISS but inside the 2·tol promotion window), so the
  pipeline would promote it.
- Position edge: most per-camber maxima sit at p 0.25, the bottom of the requested range
  (`WingParams` allows 0.20). A supplementary p 0.20 slice (35 geometries, same settings; 2 of 1,435
  points did not converge at any ladder level) gives gated Cl_max 1.938 (m 0.09, t 0.0955, alpha
  10.75) < 1.979, so the overall maximum lies between p 0.20 and 0.30 and the edge does not cap it. p
  0.20 is higher for four cambers (0.06, 0.065, 0.075, 0.085) and adds no point to the proposed box
  (its Cd is higher, up to 0.036).

### Camber bound (0.09) — reported, not changed
Gated Cl_max by camber: 0.06 → 1.690, 0.065 → 1.764, 0.07 → 1.848, 0.075 → 1.852, 0.08 → 1.935,
0.085 → 1.917, 0.09 → 1.979. The best gated design is on the bound and the trend still rises, so the
bound **is active** for the best gated designs. The proposed target does not need it: 12 interior
points (m 0.08–0.085) are in the box, though 19 of 31 box points sit on it.

### Next (waiting for review)
- Apply the target (HARD_SPEC), add the witness as a test, then session 6's items 1–5 and the
  40-eval live run.

## Session 6 (2026-10-01): report honesty, NeuralFoil screen, analysis of the first live run

### Done
- **Report** (`write_report`, `swarm/ledger.py`): "Best passing design" (a full PASS: XFoil, not a
  fallback, PASS verdict; `ledger.passing`) is separate from "Closest candidate (did not pass)", which
  lists its failing checks (`ledger.failing_checks`, built only from ledger facts). "Best overall" /
  "Best at XFoil" are gone, as are `best_cid` / `best_xfoil_cid` in meta.json; meta now has
  `best_passing_cid`, `closest_candidate_cid`, `closest_candidate_failing` and `limits`.
  `EvalRecord.failed_checks` stores the failed numeric check names.
- **Termination**: `budget` is split into `eval_budget` (max_evals) and `wall_clock` (max_wall_hours);
  `cost_cap` was already separate. `unknown` is returned if no rule explains the stop (should not
  happen). The report prints a one-line reason plus evals / est. cost / wall clock against each limit.
- **NeuralFoil screen** (`swarm/critic/screen.py`, `SurrogateScreen` on every record with a physical
  result, any fidelity): one surrogate call at alpha, +1, +2.
  - Stall: d|Cl|/dα on NeuralFoil's Cl, same definition as the XFoil probe, ≥ 0.05/deg.
  - Separation warning: suction-side H at NeuralFoil's last BL station (x/c 0.984) ≥ 4.25.
  - Calibrated on the Re 3e5 XFoil sweep (rerun this session: 1008 points, 0 failed, 27 s;
    `scripts/calibrate_screen.py` reproduces every number). Separation: recall 0.90, specificity 0.94
    over all points (best balanced accuracy of 2.0–8.0 in 0.25 steps); near the target 94/104 and 7/65.
    Stall: blocks 345 of 390 XFoil margin failures and 7 of 426 passes; near the target (63 attached
    points) 27 of 38 and 0 of 25. 0.05 needed no change.
  - At NeuralFoil it is a `neuralfoil_screen` check (suspect → TARGET_MISS). `promotable()` drops
    screen failures, the chief brief lists them under "Blocked from promotion", and `chief.sanitize`
    turns a promotion of one into a NeuralFoil step (`promotion_blocked_by_screen` event).
  - At XFoil it is not a check (XFoil's gates stay authoritative); `compare_with_xfoil` runs and a
    `screen_xfoil_disagreement` event is logged when stall or separation verdicts differ. The report
    has a screen-vs-XFoil table.
  - **Retroactively on the live run** (scratch re-render, run dir untouched): the screen fails stall for
    every one of the 15 designs and agrees with XFoil on all 4 probed ones (NeuralFoil vs XFoil slope
    0.030/0.026, 0.014/0.015, 0.039/0.031, 0.038/0.036). It would have blocked all 4 promotions
    (gens 5, 7, 10, 12), which XFoil rejected.
- **Evolution strip**: "after" = best passing design, or "no passing design — closest candidate" with
  its failing check. "middle" = most instructive failure, never the after cid: worst measured stall
  margin, else first TE separation, else worst NeuralFoil screen, else biggest drag jump. Every recorded
  frame (strip and GIF) shows its status; green only for a full PASS.
- **Stall-margin plots**: `stall_<cid>.png` per XFoil candidate with a probe: |Cl| at α, +1, +2, each
  secant against the threshold slope, TE separation points, NeuralFoil screen overlaid. Linked from
  report.md; XFoil rows without a probe say why.
- Tests: 174 → 197 (`tests/test_screen.py`, `tests/test_report.py`, more in `tests/test_viz.py`).

### Hard demo changed (mock)
`make demo-hard` now never reaches XFoil: 25 NeuralFoil evals, termination `plateau`. The mock's
alpha-led path sits at alpha 9.1–9.5° on 6–8% camber, where NeuralFoil and XFoil both see no margin
(sweep: m 0.06 / p 0.4 / t 0.0955 peaks at 8.5° and separates from 9°), so every near-target candidate
is blocked. `tests/test_demo_hard.py` now checks that. The TE-separation and stall-margin paths at
XFoil are still covered by `tests/test_stall_margin.py`. `make demo` (default preset) is unchanged:
target_met in 4 evals with real XFoil, no disagreement.

### Analysis of the first live run (no code change; heuristics table untouched)
Per generation (ledger + traces): params, the Chief's focus_params, and each CAD change against the
heuristics offered in its brief and the NeuralFoil sensitivities.

| gen | m | p | t | α | focus_params | CAD change(s) vs heuristic |
|---|---|---|---|---|---|---|
| 0 | 0.060 | 0.400 | 0.100 | 8.000 | camber, alpha, thickness | baseline |
| 1 | 0.0735 | 0.400 | 0.100 | 9.631 | camber, alpha, thickness | INSUFFICIENT_LOADING: camber +, alpha + (both follow) |
| 2 | 0.0709 | 0.400 | 0.110 | 9.631 | camber, thickness, alpha | EXCESS_PRESSURE_DRAG: thickness + (**against** "thinner"), camber − |
| 3 | 0.0715 | 0.400 | 0.125 | 9.631 | thickness, alpha, camber | EXCESS_PRESSURE_DRAG: thickness + (**against**), camber + |
| 4 | 0.0745 | 0.400 | 0.117 | 9.031 | thickness, camber, alpha | EXCESS_PRESSURE_DRAG: thickness −, alpha − (follow), camber + |
| 5 | (promotion of gen 4 to XFoil) | | | | alpha, camber | none |
| 6 | 0.078 | 0.400 | 0.117 | 9.031 | camber, alpha, thickness | INSUFFICIENT_LOADING: camber + (follows) |
| 7 | (promotion of gen 6 to XFoil) | | | | camber, alpha | none |
| 8 | 0.082 | **0.368** | 0.117 | 8.531 | alpha, camber, **camber_pos** | EARLY_STALL: alpha − (follows), camber +, camber_pos − (none offered) |
| 9 | 0.078 | 0.400 | 0.112 | 9.075 | camber, alpha, thickness | EXCESS_PRESSURE_DRAG: thickness − (follows), alpha + (**against**) |
| 10 | (promotion of gen 9 to XFoil) | | | | camber, alpha | none |
| 11 | 0.0806 | 0.400 | 0.117 | 8.531 | camber, **camber_pos**, alpha | EARLY_STALL: alpha − (follows), camber +; camber_pos unchanged |
| 12 | (promotion of gen 11 to XFoil) | | | | alpha, camber, thickness | none |
| 13 | 0.0809 | 0.400 | 0.125 | 8.531 | camber, alpha, thickness | EARLY_STALL: alpha −, thickness + (both follow), camber + |
| 14 | 0.0773 | 0.400 | 0.117 | 8.551 | camber, alpha | NONE (no heuristics): alpha −, camber − |

- **Sensitivities: never overridden.** In all 22 changes the CAD's predicted (dCl, dCd) signs equal
  the signs implied by the NeuralFoil sensitivities in its brief. It went **against the heuristic 3
  times** (gens 2, 3: thicker despite "thinner cuts drag"; gen 9: alpha up despite "lower incidence"),
  and in gens 2–3 its note says it followed the sensitivities over the heuristic.
- **camber_pos moved once, forward** (gen 8, 0.40 → 0.368). The Chief's hypothesis that generation said
  "nudging camber_pos **aft**"; the CAD moved it forward, citing the separation-bubble location, with no
  heuristic offered for it. Gen 9 did not reverse it: it branched from the best record (`01ee6bd07c`,
  p 0.4). In gen 11 the Chief asked for camber_pos "forward" and put it in focus; the CAD left it alone.
- **"TE_SEPARATION_MAIN → move camber forward" was never used.** No verdict in the run was
  TE_SEPARATION_MAIN: XFoil never separated at a design alpha, only at the stall probes (+1/+2), and
  those failures were diagnosed EARLY_STALL, whose heuristics are alpha − and thickness +. The other
  rule with camber_pos − (EXCESS_PRESSURE_DRAG) was offered only when camber_pos was not in focus,
  so it was filtered out.
- **focus_params** (Chief traces, no coercions logged): main_camber_pos chosen only in gens 8 and 11.
  Flap/gurney/slot are not free for `wing_1el`.
- Two more things the traces show: the CAD brief pairs the *latest* verdict with the *base* design
  (the best record), which can be a different candidate. The gen 9 CAD note says the diagnosis
  "appears to be a different candidate"; gen 14's acts on gen 13's overshoot. And because the base is
  the best record by objective, gens 8, 9, 11, 13 and 14 all branched from the stall-failed `01ee6bd07c`.

### Known issues / limits
- The screen is calibrated at Re 3e5 only (the default preset runs at 8.3e5; it agreed with XFoil there
  in the demo, but that is one run).
- It gates **promotion** only. A Chief that sets fidelity=xfoil without promote_cid (gens 13 and 14 of
  the live run) evaluates a fresh CAD proposal straight at XFoil; the screen is computed and compared
  there, but does not block.
- `suggest_diagnosis` does not use the screen or the XFoil stall margin, so an in-box design failing
  either gets symptom NONE from the deterministic suggestion (the LLM Critic chose EARLY_STALL itself in
  the live run; the mock does not). Changing that would change which heuristics are offered.
- The CAD's base is still `best_record` by objective, so a stall-failed design can keep being the
  parent (above). Not changed: it is a search-behaviour change, not a reporting one.
- Session 5's chief-brief gap (stall slope not shown in its tables) is unchanged, except that blocked
  promotions are now listed with their reasons.

### Next
- Rerun the live command: `python -m swarm.run --llm anthropic --preset hard --max-evals 15 --budget-usd 2`.
  Expect blocked promotions instead of XFoil stall-margin rejections; check `screen_xfoil_disagreement`
  events and whether the CAD now moves camber_pos or lowers alpha further.
- Decide on the three behaviour questions above (screen on direct XFoil steps, diagnosis from the screen,
  CAD base selection) before or after that run.
- Milestone 2 is still not started.

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
  alpha (`SINGLE_ELEMENT_PARAMS`). camber_pos stayed 0.4 in 14 of 15 designs (gen 8 tried 0.368;
  gen 9 restarted from the best record, which had 0.4; see session 6), thickness stayed 0.10–0.125,
  and camber topped out at 0.082. The sweep in session 3 says
  attached designs exist at higher camber and a more aft camber position (m 0.09, p 0.5, alpha ~6.5 —
  attached but without stall margin, so this is wrong; see session 7:
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
designs the sweep says exist (m 0.09, p 0.5, alpha ~6.5 gives Cl −1.78 at Cd 0.016 — attached at
that alpha but with no stall margin; corrected in session 7).
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
