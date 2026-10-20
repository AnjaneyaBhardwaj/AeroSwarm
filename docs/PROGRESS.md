# Progress

## Session 18 (2026-10-19): viewer redesign: headline first, calm replay, details collapsed

The page showed everything at once (three dense columns plus a ticked timeline); on a phone the result and the
story sat far down. Front end only (`viewer/index.html`, `style.css`, `app.js`); no exporter, server or data change.

### Done
- **Headline first:** what the project is (one-sentence lede naming the Chief → CAD → solvers → Critic loop), the
  result from the export's `outcome` (target met in N evaluations, final Cl and Cd tiles against the target band
  and drag cap, "confirmed by XFoil at generation N with a healthy stall margin", est. cost; or the closest design
  and its first failing check), mock / invalid-LLM labels, and one "Watch the replay" button (plays from gen 0 and
  scrolls the replay into view when it is off screen). The first-visit intro dialog no longer opens by itself; it
  stays behind the ? button (`?intro=1` opens it).
- **Calm main view:** wing and polar side by side (stacked on phones: wing, controls, polar), the generation's story
  above them, controls below (prev / play / next, scrubber, speed, Start → final). The page opens on the last
  generation, paused (`?autoplay=1` plays from the start). Removed: the in-stage final banner (its facts are in the
  headline, its CAD links in Details), the coloured timeline ticks, the restart button. Cl / Cd readouts turn green
  inside the target (BLUEPRINT §5). The run selector shows only when the gallery has more than one run.
- **One line per agent step** ("What each agent did"): Chief, CAD, Optuna, Solver, Critic, Events, each written by
  code from the export's structured fields (focus directions, promotion, accepted changes with old → new values,
  rejection reasons, Chief/CAD disagreements, ledger numbers and failed checks, Critic status/symptom/confidence,
  event names). **"Show reasoning"** reveals the verbatim text under each line (hypothesis, focus, parent choice,
  every CAD attempt with mechanisms, overrides, rejection and the CAD `note`, all evaluations with failing checks,
  all Critic evidence, event details such as the NeuralFoil/XFoil stall slopes); opening it pauses playback.
  The CAD `note` was exported but never shown before.
- **Details** (closed `<details>`): start-design dials and nearest start, live-run panel, target and run facts,
  Optuna comparison, CAD downloads.
- Live mode: the headline shows "Live run in progress" with the latest Cl/Cd and the spend line ("Follow the run");
  Stop moved onto the "now" line above the wing; "Start a live run" link under the headline (only when a live
  server answers) opens Details at the panel; a failed run says so in the headline.
- **Fixed (older bug):** when code rejected every CAD proposal and made the step itself (`cad_fallback`), the story
  described the last *rejected* proposal as the CAD agent's change (e.g. "raised angle 10.52 → 10.66°" when the
  evaluated design had 10.49°). Story and CAD line now say code rejected the proposals and describe the evaluated
  design against its parent, from the ledger.
- docs/DEPLOY.md, GitHub Pages section: the CNAME name is `aeroptimize`, not `aeroswarm`. viewer/README.md describes
  the new layout and URL options.

### Tested
- Headless Chromium at 1440×900 and 390×844, light and dark: no horizontal scroll, no page errors; reasoning,
  Details, Watch (plays from gen 0; on a phone scrolls the replay to the top), Start → final, keyboard.
- The story of all 23 generations of `example_hard_llm` matches the previous page word for word, except the new
  pointer "its reason is under “Show reasoning”" (was "in the feed") in gens 9, 10, 11, 20.
- A 6-evaluation mock live run through the page on the local server (no API key set): headline progress, Stop
  button, result in the headline when done, run joins the gallery and the selector appears; the fallback
  generation reads correctly. Its files were deleted afterwards (git-ignored anyway).
- `pytest -m "not xfoil"`: 373 passed, 1 skipped. ruff clean.

### README replay GIF (same session, after PR #20 merged)
- `swarm/viz/replay_gif.py` + `scripts/replay_gif.py` (`make readme-gif`): a viewer export becomes
  `docs/media/replay-{light,dark}.gif` (960×410, about 14 s per loop, 0.4 MB each), shown at the top of the README
  through `<picture>` (GitHub picks the variant for the reader's theme) and linked to the live site. Each frame: the
  wing (dashed start outline, downforce arrow against the target tick) beside the Cl–Cd polar filling in, a
  "Generation N of 22" header with the status pill and Cl / Cd / solver readouts (green inside the target, as on
  the page), and a footer with the goal, then the result from the export's `outcome` on the final hold. Colours
  are the viewer's tokens; Inter where installed, else DejaVu.
- Honesty rules from BLUEPRINT §5: the morph between generations interpolates `WingParams` and rebuilds the outline
  with the exporter's own `outline()` (every in-between shape is a valid section); in-between frames are labelled
  "interpolated shape → generation N" and carry no numbers of their own (header, polar and arrow stay on the last
  recorded generation). No morph between two frames of the same design (an XFoil check); its time goes to the hold.
- GIF writing: one shared palette (median cut over sampled frames) plus the theme's colours reserved exactly, and
  an exact numpy nearest-colour mapping (Pillow's own palette conversion shifted colours by a level or two, and a
  status colour missing from the sample came out brown). Pillow is now a declared dependency (it was already
  installed through matplotlib; same locked version).
- `tests/test_replay_gif.py` (10): plan (each generation held once, loop length fixed, skipped morphs), every
  number equals the headline record, the final footer from `outcome` (also no-pass and mock), status labels,
  morph through parameters equals `outline(blend)`, exact reserved colours, both themes written and readable,
  and the README alt text matches the export. Full suite: 383 passed, 1 skipped.
- The older `evolution_morph.gif` (per run directory, engineering view) is unchanged.

### "How it works" page (same session, after PR #21 merged)
- The user asked for a separate, fun page that explains the project to everyone, with the agents personified: the
  Chief looking like a chief, the CAD agent wearing glasses, the Critic with a magnifying glass. A preview was
  approved first (one change: the machines' label).
- `viewer/about.html` + `viewer/about.css`, linked as "How it works" from the replay page's header (the page links
  back with "Watch the replay"). Sections: headline and team photo; the job (why a race car has an upside-down wing,
  the brief, a cartoon car carrying the run's real final wing section); meet the crew (the Chief: team-boss cap with
  an airfoil badge, headset, moustache, clipboard; the CAD Engineer: round glasses, pencil, tablet showing the real
  start wing; the Critic: beret, raised eyebrow, magnifying glass); the machines, labelled "not agents" (the Hare =
  NeuralFoil, "a small neural network trained on the Tortoise's answers"; the Tortoise = XFoil, the only one that
  makes a design official; the Referee = the rule checks, showing red cards); a four-panel comic of generation 1
  (real numbers, dialogue marked as dramatised, pointing to "Show reasoning" for the agents' own words); how it
  ended, with the Optuna rival and its fine print; house rules; a pocket dictionary.
- Characters and machines are inline SVG symbols in the site's tokens (light and dark), with idle motion (bob,
  blink, the magnifier's sway, air over the car) that stops under prefers-reduced-motion. Fonts: Bricolage Grotesque
  (headings) and Patrick Hand (speech bubbles) from Google Fonts, Inter and JetBrains Mono as on the replay page.
- `tests/test_about_page.py` (5): every number on the page against the export (result, cost and time, the brief,
  the comic's generation-1 plan, sketch, red-card millimetres, estimate, shortfall and diagnosis, the rival's 40
  tries), the drawn wings equal the run's outlines, and the pages' links and files exist.
- Browser-checked at 1440 and 390 px, light and dark: no sideways scroll, no failed loads or page errors.

### The explainer is the home page (same session, after PR #22 merged)
- The user wants "How it works" to be the first thing every visitor sees. `viewer/about.html` → `viewer/index.html`
  (home), the replay `viewer/index.html` → `viewer/replay.html` (title "Aeroptimize Replay"). The brand links home
  on both pages; the replay's "How it works" links to `./`; the home page's buttons go to `replay.html`.
- Old links keep working: the home page forwards any `?run=` / `?gen=` / `?autoplay=` / `?speed=` / `?intro=` link
  to `replay.html` with the same query (shared replay links from before), and `about.html` is now a stub that
  forwards to `./` (it was live for a few hours).
- Live mode: the replay with the Live run panel is at `/replay.html` (docs/DEPLOY.md, viewer/README.md, Makefile,
  `swarm/live.py` updated; layout B's `aeroswarm-api` meta tag is in `replay.html`). `tests/test_live.py` checks the
  server serves it; `tests/test_about_page.py` checks the links and both forwards.
- Browser-checked: home → replay → home, an old `/?run=…&gen=5` link opens generation 5 of the replay, `/about.html`
  lands on the home page; no page errors.
- The car drawing's dashed pointer ("the bit the crew designs") now ends in an arrowhead on the wing, its tip just
  above the wing's top edge (taken from the run's outline), at the request of the user.

### Framing: it's the wing's cross-section (same session, after PR #24 merged)
- The user asked whether to say explicitly that only the airfoil is optimized. Yes, once and plainly (aero reviewers
  check 2D vs 3D at once; a clear scope reads as confidence). Previewed and approved first.
- Home page: the hero says the crew redesigns "the cross-section of a race-car wing"; a "What exactly do they
  design?" box explains the airfoil as a slice of a loaf (flat, 2D, no span, no end plates, not the car; the 3D wing
  is a later step), with a drawing of the wing as a loaf of the run's real final section and one slice pulled out;
  the brief says its numbers are for the slice at 15 m/s (54 km/h) on a 300 mm chord; the car label reads "the slice
  the crew designs"; the dictionary adds Airfoil and Chord (8 terms, 4 columns). Replay page: "designs a race-car
  wing section" (headline and the "How to read" dialog).
- `tests/test_about_page.py`: the stated speed and chord are the run's and give its Reynolds number by the project's
  own formula (`AIR_KINEMATIC_VISCOSITY`).

### Emil Kowalski's design skills (session 19, 2026-10-20)
- The user ran `npx skills add emilkowalski/skill`: 15 project-level agent skills (animation, interface design, UI
  stress tests, library picks; a few for Expo/Swift that this project does not use) in `.agents/skills/`, linked
  for Claude Code from `.claude/skills/`, pinned by hash in `skills-lock.json` (`npx skills experimental_install`
  restores them). Reviewed before committing: markdown only, no scripts; the only commands are `npx expo install`
  lines for Expo projects; links go to documentation sites. Nothing in the swarm, the site or CI depends on them.
- Then `npx skills add Leonxlnx/taste-skill`: one skill, `design-taste-frontend` (art direction for public web pages
  and app screens), same layout. It ships code: Node scripts and data (2.5 MB). Reviewed: `inspect.mjs`/`scenes.mjs`
  serve the page on 127.0.0.1 and drive a throwaway headless Chrome profile (Node 22+); `assets.mjs` searches and
  downloads openly licensed images (Openverse, Wikimedia Commons, Art Institute of Chicago, the Met, Internet
  Archive, NASA) with GET only, no keys, only when run; `draw.mjs` keeps a local history in
  `~/.taste-skill/history.json`. No uploads, no credential access, nothing runs on install.

### Design review fixes: the real thing on the home page, a calmer replay (session 19)
After running `design-taste-frontend` on both pages (home: 12 FAIL; replay: 2 FAIL). Front end and the GIF script
only; no exporter, server or data change.
- **Home page, real pictures from the run:** new section "The Tortoise catches one" with the run folder's own
  stall charts (`viewer/media/stall_<cid>.png`, byte-identical copies): in round 7 the NeuralFoil screen passed
  `81b3351c10` at 0.052/deg (bar 0.05), in round 8 XFoil re-tested the same design at 0.034 and sent it back; the
  final `abb9803ead` has 0.068. The replay GIF plays in the closing "Now watch them do it" section (light or dark
  copy by theme).
- **Home page flipbook** ("How it ended", `viewer/about.js`): a slider and play button over all 23 tries, reading
  the export (`runs/example_hard_llm.json`): the try's outline against the dashed start, push and drag bars
  against the target band and drag limit, which machine measured it, and a plain verdict built from the record
  ("Not yet: 0.198 short on push and close to stalling."). Plays through once when first in view (not with reduced
  motion). Without the export the static start-and-final picture stays.
- **Replay:** Cd to 4 places everywhere (was 4 in the headline and story, 5 in readouts, steps and tooltips).
  Polar: target misses grey, NeuralFoil-only passes amber, full pass green, failures red; the overlapping "Optuna"
  text is gone (the legend names the diamond); the legend lists only the result kinds and solvers the run has; the
  "target box" label sits inside the box at the empty low-drag end. Sentence-case labels and status chips instead
  of tracked capitals ("Target miss", "Pass at NeuralFoil only"); `--ink-3` darkened to 4.5:1 or better on every
  surface in both themes; dial units 11px; no eyebrow; title 24–29px; the result numbers (34px) are the largest
  type. The lock emoji on locked focus parameters became "(locked)". Inspector: 0 FAIL, 1 WARN.
- **README GIF** regenerated in the same style (grey misses, Cd to 4 places, sentence case, legend of what is
  present, results on one row and solvers on the next) and moved from `docs/media/` to `viewer/media/`, so the
  site serves the same files; README, `make readme-gif` and the script's default follow.
- Tests: `test_about_page.py` checks the stall-chart text against the export and the charts against the run
  folder, and the flipbook's try count. `pytest` (XFoil installed): 398 passed, 1 skipped; ruff clean.

### Stale stylesheet after the deploy (session 19, after PR #26 merged)
- Right after the merge the user saw the new home page with the old `about.css`: both replay GIFs stacked at full
  width, the stall chart full width, the flipbook unstyled. Cause: GitHub Pages serves files with a 10-minute
  browser cache, so the old stylesheet was reused with the new page (reproduced locally by serving the new
  `index.html` with the pre-merge `about.css`). A hard refresh fixes it for one visitor.
- Fix for every visitor: the pages link their own CSS, JS and pictures as `file?v=<first 10 hex of its sha256>`
  (`swarm/viz/stamp.py`, `scripts/stamp_assets.py`, `make stamp`; `make readme-gif` re-stamps). A changed file
  gets a new address. `tests/test_viewer_stamps.py` fails while a stamp is stale; the link test ignores the
  stamp. The flipbook fetches the export with `cache: "no-cache"`, as the replay does.

### Replay headline: no run-label chip (session 19)
- Removed the "LLM swarm (anthropic:claude-sonnet-5)" chip under the replay's lede, at the user's request (with its
  code and `.chip.mock` styles). A mock run stays labelled: the headline note says "Mock run: ..." for recorded
  runs and now also while a live run is going. The run selector (shown only with more than one run) still names
  each run.

### Home page: wavy air in the margins, name in the footer (session 19)
- Small wavy lines (three little waves each, the accent colour) drift left to right across wide screens: in from
  the left margin, faded out by a CSS mask before the 1080px text column, back out on the right. 24 lines in three
  depths (small, faint and slow to bigger, stronger and quicker; 14–31 s per crossing). One `#squiggle` symbol in
  the sprite; each line is its own `<svg>` moved by a transform-only animation, so no repainting. Shown from
  1360px wide (narrower screens have no margins); hidden for reduced motion. The user first saw moving dashed
  streamlines and asked for small wavy lines instead.
- Earlier the same day the header's "Watch the replay" link and the footer tagline went; the footer now reads
  "Aeroptimize · by Anjaneya Bhardwaj".

### Rulebook: FSAE 2027 in the docs and on the site, and an audit of the check (session 19)
- `docs/BLUEPRINT.md` "Regulation compliance" now describes the Formula SAE Rules 2027 v1.0 (read from
  `docs/FSAE_Rules_2027_V1.pdf`: T.7.1.4/.5, T.7.3–T.7.7, V.1.1, V.1.4.1) as the default, with what the 2D check
  covers; Formula Student 2026 stays as the alternative the committed example run used. `DesignSpec` block, table
  of contents, appendix and sources follow. README notes the example run's rulebook.
- Home page: the brief says "Legal under the Formula Student 2026 rules" (the run's own rulebook); a note under
  "How it ended" says the project now follows FSAE 2027 (5 mm front-edge radius instead of 3 mm) and new runs start
  thicker. Replay Details show the rulebook's name instead of its code. `test_about_page.py` checks both against
  the spec, `RULEBOOKS` and `check_regulations`.
- **Audit (read-only; the FSAE code is frozen):** limits and rule numbers match the PDF, and every design the swarm,
  the inner loop and the live pre-check evaluate is rule-checked before it is solved. Gaps, written up under
  "Known gaps" in the blueprint: (1) T.7.1.4 uses the NACA formula r ≈ 1.1019 t²c; measured on the generated
  outline, cambered noses are tighter (the example's final wing 4.94 mm vs 5.59 mm by formula; 201 of 1,260
  formula-legal grid sections under 5 mm; both preset starts measure 5.29 mm, fine); (2) T.7.1.5 is a thickness
  check, the TE is a flat cut with square corners; (3) not checked in 2D: width, end plates, V.1.1, dynamic ground
  contact; (4) placeholder car; (5) the Optuna baseline does not rule-check its first design.
- Against this file's history: (3) and (4) were known since session 12 and deferred by the user in session 14;
  (2) is session 1's deliberate threshold. (1) and (5) are new. Session 12 checked the NACA formula's
  coefficients (and the generator against AeroSandbox), not the built outline's nose, so its "all 7 XFoil winners
  are FSAE-legal (LE radius 5.6–6.2 mm)" is by formula; the example winner measures 4.94 mm. A fix to (1) reaches
  session 12's hard-target derivation: measured, all t 0.125 sweep shapes, 13 of 49 at t 0.13 and 2 of 49 at
  t 0.135 fall under 5 mm (t ≥ 0.14 unaffected; the witness measures 5.35 mm). The sweep data is not committed;
  re-running it is XFoil only.

### Next
- Decide whether to fix the T.7.1.4 check (measure the nose radius on the outline). It changes which designs are
  legal under FSAE 2027 and means re-checking the hard target's box (re-run the gated sweep, XFoil only), so it is
  the user's call (research features are frozen).
- Home page, still flagged by the inspector: the 3-line headline, the eyebrow, monospace numbers, small uppercase
  labels, a resting shadow, hairlines, 1px-outlined boxes, text under 13px, no single focal point on the first
  screen. It counts 3 real pictures and wants at least 4: photo archives (Wikimedia, Openverse, NASA, ...) are
  blocked by this cloud environment's network policy until the user allows those hosts.
- 2-3 more recorded runs in the gallery; one real-Claude live run on the Mac (asks before spending credit). Still
  never tested: the Dockerfile's XFoil stage, the Mac setup, a real-Claude live run. When a new run joins the
  gallery, `scripts/replay_gif.py viewer/runs/<name>.json` makes its GIF.

## Session 17 (2026-10-15): run viewer for the portfolio, part 1 (exporter + gallery replay)

New priority from the user: a visual run viewer. **Research features are frozen** (no FSAE preset work, no
OpenFOAM work) until the viewer is done.

### Done
- `swarm/viz/export.py` + `scripts/export_run.py <run_dir>...`: one run directory becomes `viewer/runs/<name>.json`,
  and `viewer/runs/index.json` is rebuilt. It holds the spec and target, the start params, and per generation: the
  parent choice, the Chief's hypothesis, focus directions and the mode/fidelity actually executed, every CAD attempt
  (changes, mechanisms, override reasons, Chief/CAD disagreements, rejection reason), every evaluation (params,
  solver and ladder level, Cl, Cd, verdict, failing checks from `ledger.failing_checks`, stall margin from the
  XFoil probe or else the NeuralFoil screen), the Critic's diagnosis, and notable events (overrides, screen/XFoil
  disagreements, recoveries, inner-optimizer summaries, LLM failures). Numbers come from the ledger; agent text is
  verbatim from `traces.jsonl` (cut at a word boundary with " …", never rewritten). A trace is matched to its
  generation by the first later event from its role's node. A failed Critic call shows the numeric verdict,
  labelled. NACA outlines (race-car orientation, 81 points) are included per candidate (`cad.build.placed` takes `n`).
- Optuna comparison line: `--optuna auto` (default) runs `baselines.search("optuna")` from the same start, spec
  and budget (sampler seed = start_seed, else 0) into `runs/viewer_baselines/<name>_optuna/`, reused after that;
  `--optuna <dir>` uses an existing baseline run, `--optuna none` skips it. Caveat shown on the page: the baseline
  runs with the current pipeline code, while an older LLM run ran with the code of its day (the example run used
  Formula Student 2026 and the 0.05 screen threshold).
- `viewer/` (static HTML/CSS/JS, no build step): `make viewer` serves it on :8000. Start-design dials (drag, scroll,
  arrow keys); on release the page picks the nearest recorded start (RMS of range-normalised differences), says which
  run and how far, and replays it. Replay: the wing tweens between generations with the parent ghosted and a
  downforce arrow ∝ |Cl| against the target; dials follow the params; the agent feed shows the generation's Chief /
  CAD / solver / Critic text; the Cl–Cd polar fills in with the target box, status colours (with icons and labels) and
  NeuralFoil/XFoil shapes; scrubber, step, 0.5–4× speed, keyboard; final banner (target met, or "no passing
  design" with the closest candidate's failing checks; mock and invalid-LLM runs labelled); start→final morph.
  Readouts snap to recorded values; only animation frames are tweened. Dark/light themes, works at phone width.
- `tests/test_export.py` (6 tests: ledger numbers, verbatim text, CAD outcomes/overrides, outlines, index, baseline).
- Exported: `viewer/runs/example_hard_llm.json` (the committed example run; Optuna from the same start: no pass in
  40 evaluations, closest Cl −1.8271 / Cd 0.0205 at NeuralFoil).

### Known issues / gaps
- `docs/viewer-prototype.html` (the design reference) is not in the repository on any branch, so the page layout is a
  new design; align it with the prototype once it is committed.
- The bench3 LLM runs (`runs/bench3/llm_s33`, `_s44`, `_s55`) are not committed; until they are exported
  (`uv run python scripts/export_run.py runs/bench3/llm_s33 runs/bench3/llm_s44 runs/bench3/llm_s55`, which runs
  Optuna for seeds 33/44/55 from the same starts) the gallery holds one run, so the nearest-start search always
  picks it.

### Part 3: live mode (same session)
- Cost check first, from the recorded runs: LLM-only ≈ $0.06–0.09 per evaluation on Sonnet (example run $1.47 / 23
  evaluations, 17 min; bench3 $2.45–2.98); hybrid $0.61–0.68 per 40-evaluation run. The repo default model
  (`claude-opus-5-5`) costs twice Sonnet per token. Decision: the public page replays only; live runs only through
  the local server, capped, Sonnet 5.5 by default.
- `swarm/live.py` (FastAPI, `make live`): serves `viewer/`; `POST /api/check` runs the start design through the
  run's own geometry/rule checks; `POST /api/runs` starts `swarm.run.run` (hard preset, the dial values as the start)
  in a thread with caps (≤ 40 evaluations, ≤ $5 via `max_cost_usd`, 30 min, one run at a time) and returns an
  estimate; `GET /api/runs/{id}/stream` (SSE) re-exports the run directory with `export_run` and sends `run`, each
  complete `generation` (complete = a later generation has started, or the run ended), `progress` (evaluations,
  spend, calls, time) and `done` (the full export with the Optuna comparison, also written to `viewer/runs/live/`,
  git-ignored) or `error`. `/runs/index.json` merges the committed gallery with finished live runs.
- Viewer: a "Live run" panel appears only when `api/health` answers (agents Claude/mock, model with $/evaluation,
  evaluations, cost cap, hybrid; live rule check on every dial change; estimate; status line with spend). The
  replay engine follows the stream; leaving for a recorded run detaches without stopping the server run, "Back to
  it" re-attaches. When the run ends it is selected in the gallery.
- `tests/test_live.py` (3 tests, mock, offline): health/static, request validation and the rule check, and a full
  streamed run whose generation records equal its saved export. Browser-checked with a mock run.
- Found while testing: the committed example run's start (thickness 0.10, Formula Student 2026) fails FSAE 2027
  T.7.1.4 (LE radius ≥ 5 mm needs thickness ≥ 0.123), so a live run from the default dials is refused; the panel
  now says so before the click.

### Self-explanatory demo (same session)
- Intro dialog on the first visit ("How to read this replay"; the ? button reopens it): the goal filled from the run's
  spec, the Chief → CAD → solvers → Critic loop, what each panel shows; "Watch the replay", or "Start a live run"
  when the local server is up. Remembered per browser; `?intro=0` skips it.
- A caption per generation above the wing, generated from the export's facts only (never paraphrasing agent text):
  what kind of step it was (start, CAD change with old → new values, XFoil verification, Optuna search), why code
  rejected earlier proposals (duplicate / Chief's limits / geometry or rulebook), whether the CAD overruled the Chief
  (from the code's disagreement record, not from the presence of an override reason), the solver's numbers and in
  plain words why it is not a pass, and the Critic's symptom.
- Hover/focus explanations on the jargon (Cl, Cd, solver, stall margin, polar, dials, target, feed, each agent).
- Default replay speed 1× (about 1 minute for the example run). Live panel: one-line rule message with
  "Use the preset start" (`/api/health` returns `default_start`, the hard preset's start).
- Fixed: `[hidden]` now always hides (the intro's `display: grid` had kept a closed intro over the page); phone header
  no longer overflows.

### Stop button and "now" line (same session)
- `TraceLogger.request_stop()`; the graph's `capped()` is also true once a stop is requested, so a stop takes the
  cost-cap path (no further LLM call; an in-flight candidate is still solved and recorded) and ends with the new
  termination `stopped` (`termination_reason(..., stopped=True)`, event `stopped_by_user`). `POST
  /api/runs/{id}/stop`; the page's Stop button. Tested in `test_report.py` and `test_live.py` (a mock run stopped
  early ends `stopped` and is saved).
- `progress` events carry `gen` and `phase` (from the newest event's node: "The CAD agent is choosing the change",
  "The solver is running", "The Critic is reviewing the result", ...); the page shows it above the feed with a
  spinner, so a real-LLM generation (30-60 s) never looks frozen.

### Deployable on the user's own website (same session)
- The user will host it on their own site. The Artifact link stays replay-only (its frame blocks requests to
  any server).
- Server: `AEROSWARM_LIVE_ACCESS_CODE` (needed to start a real-LLM run; mock runs stay open),
  `AEROSWARM_LIVE_DAILY_USD` (`DailySpend`: a run reserves its cap at start, the unused part is returned at the
  end; kept in `runs/live/_daily_spend.json` across restarts), `AEROSWARM_LIVE_ORIGINS` (CORS for a page on
  another origin), a per-run control token for Stop, `X-Accel-Buffering: no` on the stream, `--proxy-headers`,
  and `main()` refuses a non-local bind without an access code unless `--allow-open`. `/api/health` reports
  `xfoil` (without it no run can pass; the page says so) and the daily budget.
- Page: `<meta name="aeroswarm-api">` for a separate API origin (then the gallery comes from the server's merged
  index), an access-code field when required, today's remaining budget in the estimate.
- `Dockerfile` (XFoil built in a builder stage, non-root runtime, health check, volumes for runs and the live
  gallery), `.dockerignore`, `docs/DEPLOY.md` (layouts, settings, safety rules, nginx/Caddy, no-Docker path).
- Tested: 4 new server tests (access code, daily cap reserve/settle/restart, CORS, public-bind refusal). The
  image was built and run here without its XFoil stage: refuses to start without a code; with one, serves the
  page, refuses a wrong code, streams a mock run (8 generations) and adds it to the gallery, runs as non-root.
  **The XFoil build stage is untested**: this sandbox's network policy blocks deb.debian.org.

### Subdomain deployment (same session)
- The user chose layout A on a subdomain. `deploy/docker-compose.yml` (the app plus Caddy for automatic HTTPS;
  Caddy waits for the app's health check, which takes about 20 s), `deploy/Caddyfile`, `deploy/.env.example`
  (`deploy/.env` git-ignored); docs/DEPLOY.md "Subdomain on a server" (VPS, DNS A record, `.env`, one command).
- Tested here with the XFoil-less test image and `DOMAIN=localhost` (Caddy's self-signed certificate): page over
  HTTPS, HTTP redirects to HTTPS, a mock run streamed through Caddy (6 generations), the finished run still in the
  gallery after an app restart. Not testable here: a real certificate (needs a public domain) and the XFoil stage.

### FreeCAD: CAD files for every run (same session)
- The user asked for a real CAD program; FreeCAD chosen (free, scriptable, runs headless on a server). Architecture
  rule kept: no agent sees or drives FreeCAD. After a run, deterministic code (`swarm/cad/freecad_export.py`) takes
  the start and the final design (best passing, else closest candidate, labelled so) and runs
  `swarm/cad/freecad_doc.py` inside `freecadcmd` (FreeCAD's own Python): a document with each section as a closed
  B-spline face through the solver's points plus its chord line, at the real 300 mm chord in race-car orientation,
  and a "Design" spreadsheet of parameters and ledger results; a STEP file of the two faces; the final section's
  Selig `.dat`. Sections stay 2D, as optimized: no invented span (the user's point).
- Checks before a file is offered: each face valid and its area within 0.5% of our polygon area; the STEP file read
  back as the same two faces. The first version failed this check by 6.4%: FreeCAD's `Face.Area` integrates a
  321-knot B-spline boundary badly, while the meshed face matches to 0.005%, so the check meshes the face. The
  geometry was right; the check caught the measurement.
- Wiring: `scripts/export_run.py --cad auto|none` writes `viewer/runs/<name>_cad/`; the live server does the same
  for every finished run (`live/<name>_cad/`); the export's `cad` block lists the files; the page shows download
  links in the final banner and the Run panel. `/api/health` reports `freecad`. Example run re-exported with them.
- Docker: a `mambaorg/micromamba` stage installs pinned `freecad=1.1.3` from conda-forge (the newest conda build is a
  dated development snapshot, avoided); `WITH_FREECAD=0` leaves it out. Image about 7.2 GB without XFoil here.
- Tested: FreeCAD 1.1.3 headless here (micromamba, since Ubuntu 24.04 has no FreeCAD package); `tests/test_freecad_export.py`
  (4 tests without FreeCAD, 1 that needs it and skips on CI); a mock live run in the browser ended with its three
  files and the STEP downloaded; the image with the FreeCAD stage (XFoil stage skipped, blocked mirror) built and ran
  as non-root: a mock run produced checked CAD files served over HTTP.

### Mac: local live runs in Docker (same session)
- The user will start with a replay-only public site and live runs on their Mac. conda-forge has no XFoil (FreeCAD
  1.1.3 exists for osx-arm64/osx-64/linux-aarch64), and `scripts/install_xfoil.sh` is Debian/Ubuntu-only, so the Mac
  route is the existing Docker image under Docker Desktop: `deploy/docker-compose.local.yml` (localhost-only port,
  `--allow-open`, runs and gallery bind-mounted into the checkout), `make local-live`, `make local-export RUN= NAME=`.
  Every locked Python package has a linux-aarch64 cp312 wheel, so Apple Silicon builds natively.
- Found while testing it: FreeCAD 1.1.3 crashes at start-up (in `getPythonPath`) when its user ID has no account
  entry, e.g. a container run with an arbitrary `--user`. The local compose therefore keeps the image's user, and
  `freecad_export.freecad_probe()` now starts `freecadcmd` once before trusting it: `/api/health` reports `freecad`
  only when it really starts, and an export that cannot run says why instead of failing later.
- Tested here with the image minus its XFoil stage: local stack up, health `freecad: true`, a mock live run with its
  CAD files, `local-export` writing the gallery entry and three files into the checkout; and the probe's failure
  report as uid 1000. Not tested on an actual Mac.

### Name: Aeroptimize (same session)
- The public name follows the user's subdomain `aeroptimize.anjaneyabhardwaj.com`: page title, header and intro,
  README (with the live link), viewer README, FreeCAD document and spreadsheet label, the server's title, comment
  headers, and the clone URLs in docs/DEPLOY.md (`AnjaneyaBhardwaj/Aeroptimize`, for the repository rename the
  user does after merging). Kept on purpose: the `AEROSWARM_*` settings, the `aero-swarm` package and `swarm`
  module, internal markers (`aeroswarm-<cid>` in coordinate files, browser storage keys). Renaming those would
  break existing setups for no visible change.

### Known issues (live)
- No real-LLM live run has been made from the page yet (it would spend the user's API credit); only the mock.
- The Dockerfile's XFoil stage has not been built (blocked mirror here); first build is on the user's machine.
- One instance only: the active run lives in memory.

### Next
- Public site: GitHub Pages (user's choice; `.github/workflows/pages.yml` restored from ff6a8ef, one-time steps in
  docs/DEPLOY.md). Then: live runs on the user's Mac (`make local-live`); one
  real-Claude run to prove the live path; 2-3 more recorded runs exported into the gallery; a replay GIF at the
  top of the README. The Azure VM (docs/DEPLOY.md) only if always-on live runs are wanted later.

## Session 16 (2026-10-15): milestone 5 parts 2 and 3: recovery ladder, CFD agent, mesh study, graph wiring

PR #14 (part 1) merged.

### Transition model (`model="kOmegaSSTLM"`, `case.retheta_t_freestream`)
Tried first, as planned. On the witness it moves Cl from -1.44 (SST) to -1.59 (XFoil -1.82) but is not
mesh-converged (-1.53 at 480 cells around, residuals stall at 3.6 / 4.5 orders); insensitive to Tu 0.1-0.5%.
SST is mesh-converged (0.3%). **SST stays the default**; SST-LM is an option. At Re 3e5 of2d is a cross-check
with a known model-form gap (docs/OPENFOAM.md finding 5).

### Part 2: recovery ladder and CFD agent
- `swarm/solvers/openfoam/recovery.py`: L1 relaxation, L2 first-order U for 300 iterations then second order
  (`SolverOverrides.first_order_iters`, two solver stages), L3 potentialFoam + viscosity ratio 1, L4 re-mesh (first
  cell x4, growth 1.10, smoothing x8, far field 50 c), L5 drop to XFoil. Classification from the monitor signature
  (early < it 50 or checkMesh: mesh; later: numerics; persistent bounding: turbulence) and a per-class
  preference. Code forbids repeats, bounds the ladder, and allows only L4/L5 after a checkMesh failure.
- `RecoveryAction` (state.py), `swarm/agents/cfd.py` (choose / sanitize / fallback), prompt `cfd.md`,
  `briefs.cfd_brief` (signature, iteration, class, residual tail, checkMesh numbers, the failed setup, levels
  tried). MockClient answers RecoveryAction with the policy. `solver.evaluate_with_recovery` runs the ladder.
- `scripts/of_recovery.py`, `docs/OPENFOAM_RECOVERY.md`: 5 failing setups (early blow-up and late divergence from
  injected relaxation, a mesh failing checkMesh, and two divergences found by the mesh study: 160 cells around and
  growth 1.16 at Re 6e6); both policies recover all five in <= 2 levels and chose the same levels; the LLM agent
  (6 calls, $0.036) re-meshed first on the early blow-up although it cited relax_U 0.9 (the prompt's "early means
  mesh" guidance won). Part 1's crashes (thin
  first cell, 300 c far field) no longer happen with the part-1 numerics.

### Part 3a: mesh independence (`scripts/of_mesh_study.py`, `docs/OPENFOAM_MESH.md`)
One parameter at a time (cells around 160-480, first cell 1e-5 to 4e-5 c, growth 1.08-1.16, far field 50-150 c)
on NACA 0012 (Re 6e6) and the witness (Re 3e5); 20 solves.
- Witness: converged within 0.3% in Cl, ~3% in Cd (every variant within 0.014 in Cl): the Re 3e5 gap to XFoil
  is not a mesh effect. NACA 0012: cells around / first cell within 0.0015 in Cl and 2% in Cd; far field 100 c
  within 0.5% of 150 c (50 c: Cd +8.9%). Default mesh kept.
- 160 cells around and growth 1.16 diverged at Re 6e6: added to the recovery evaluation.
- Growth 1.08 ended quietly with a wrong answer (Cl 0.96, separation at 0.87) after only 4.5 orders of U drop:
  **`solver.convergence_status` now judges a quiet exit by the criteria** (`not_converged` goes up the ladder,
  `unsteady` goes to the CAD agent) instead of calling it converged.

### Part 3b: of2d in the graph
- `run(of2d=False)` / `--of2d`; state `of2d_allowed`; meta `of2d`. The Chief may set fidelity of2d only as a
  promotion of a design with an XFoil result (`of2d_needs_xfoil_result`; refused when the run does not allow it);
  its prompt describes of2d (fully turbulent, minutes, may disagree with XFoil at low Re) only then.
- `cfd_solve` at of2d runs `evaluate_with_recovery` with the CFD agent (deterministic policy on a failed call,
  counted as its fallback; coercions logged); events `of2d_recovery`, `of2d_unsimulatable`. An unconverged design
  is evaluated at XFoil with `fallback_from="of2d"` (cannot end the run). `cfd_recover` never re-runs an of2d
  result (its ladder already ran).
- Validator at of2d (`numeric.cfd_checks`): residual drop p >= 4 / U >= 5 orders (else NUMERICAL_FAILURE, or
  UNSTEADY when the coefficients still move), coefficient window <= 0.5%, checkMesh OK, mean y+ <= 5 (suspect).
  Stall probe at the result's fidelity (of2d: L0 per probe point). Report: an "OpenFOAM recovery ladder" section
  from the ledger. The CFD agent is not required for LLM validity (called only after failures).

### Tests and smoke run
`tests/test_openfoam_recovery.py` (18), `tests/test_of2d_graph.py` (5); 360 pass offline (no OpenFOAM, XFoil,
network or key). Real-solver smoke run (default preset, cl_tol 0.002 so XFoil misses, a mock that promotes the
first XFoil design to of2d once): the promotion ran OpenFOAM (184 s, converged at L0, Cl -1.310 vs XFoil -1.487);
the validator flagged fidelity_gap and te_separation; the report's OpenFOAM section came from the ledger. On the
hard preset the mock never reached XFoil (the NeuralFoil screen blocked every promotion), so of2d never ran there.

### Next
- Benchmark 4 (offline arms free; hybrid ~$5-10; LLM-only ~$40-45), then milestone 6 (diffuser: needs a ground
  plane and ride height, a new mesh topology) and the stretch goal.
- Open: the "early means mesh" guidance in the CFD prompt; SST-LM mesh convergence; of2d at Re 3e5 is a
  cross-check only.

## Session 15 (2026-10-15): milestone 5 part 1, the OpenFOAM T2 tier (mesh, case, solve, forces, validation)

PR #13 merged. The user chose to finish the remaining milestones before running benchmark 4 (offline arms free,
hybrid ~$5-10, LLM-only ~$40-45; the API works again). Milestone 5 split in three parts: (1) T2 tier and
validation (this session), (2) monitor + recovery ladder + the CFD agent's RecoveryAction, (3) mesh independence
and graph integration. The user stopped work after part 1.

### Environment
- No Docker daemon (client only); dl.openfoam.org / dl.openfoam.com are blocked by the network policy. Ubuntu's
  `openfoam` package (ESI v1912) installs; binaries on PATH, needs `WM_PROJECT_DIR=/usr/share/openfoam`.
  Added to `.claude/hooks/session-start.sh` (idempotent; reports `openfoam_missing` if it cannot install).
- `kOmegaSSTLM` (transition) is in this build.

### Code (`swarm/solvers/openfoam/`)
- `mesh.py`: structured O-grid around the section (blunt base included), written straight to polyMesh (no
  snappyHexMesh). Near the wall it marches along smoothed normals (self-repairing: a layer that would fold is
  re-marched with more smoothing); once a layer is star-shaped about an interior point it blends to pure rays,
  which cannot fold. `quality()` (non-orthogonality, folds) in Python. Default: 240 cells around, first cell
  2e-5 c, growth 1.12, far field 100 c, ~31k cells. Wall geometry saved per case (`wall_geometry.npz`).
- `case.py`: simpleFoam, k-omega SST, non-dimensional (chord 1, |U| 1, nu 1/Re), freestream at alpha,
  freestreamVelocity / freestreamPressure far field, low-Re wall treatment; `SolverOverrides` (bounded) is all an
  agent may set. p with PCG/DIC (GAMG diverges in v1912 on this mesh); k and omega first-order convection.
- `forces.py`: Cl, Cd, Cm, surface Cp / Cf and y+ from the written fields (every function object aborts in the
  v1912 package with an "sha1" IOstream error); history over the last 8 written times (every 50 iterations).
- `exec.py`: allowlisted applications (simpleFoam, potentialFoam, checkMesh), argv only, own process group,
  streamed log with an `on_line` kill hook and a timeout. Native, not containerised (see Environment).
- `monitor.py`: divergence monitor (FPE / NaN, solver blow-up, residual blow-up and growth, persistent
  bounding) with `post_mortem`; replayed on real crash logs it kills 2 iterations before the FPE. Part 2 will
  build the recovery ladder on it.
- `solver.py`: `evaluate(params, spec, run_dir, overrides, mesh)` -> `CFDResult(fidelity="of2d")` with residual
  drop orders, Cl/Cd relative std over the last 300 iterations, y+ (min, mean, max), checkMesh numbers, and the
  suction-side TE separation from Cf (excluding the TE corner cell).
- `swarm/critic/surface.py`: surface data at of2d, so the Cp-integral / Cp-spike checks apply at T2.

### Validation (`scripts/of_validate.py`, `evals/openfoam_validation.json`, `docs/OPENFOAM.md`)
- NACA 0012, Re 6e6, alpha 10: Cl 1.0916 / Cd 0.0138 vs CFL3D SST 1.078 / 0.0124 (+1.3% / +11%); far field
  carries most of the drag error (30 c gave Cd 0.0166).
- **Re 3e5 (hard preset): fully turbulent SST disagrees with XFoil far beyond the 0.1 fidelity gap.** Witness
  (m 0.085, p 0.35, t 0.135, alpha 8.75): OpenFOAM Cl -1.44, Cd 0.0436, TE separation from x/c 0.71; XFoil
  -1.82, 0.0225, attached. Model form (transition), not numerics: clean mesh, y+ < 0.5, residuals down 7 orders.

### Tests
`tests/test_openfoam.py` (32): O-grid on every FSAE-legal corner of the parameter box (no folds, non-orthogonality
< 60), polyMesh bookkeeping, wall normals, an exact force check on a synthetic pressure field, case files,
bounded overrides, monitor on recorded v1912 crash / healthy logs, log parsers, allowlist, missing OpenFOAM.
Fixtures: `tests/fixtures/openfoam/` (log excerpts). 337 tests pass without OpenFOAM, XFoil, network or key.

### Next (tomorrow, per the user)
- **Transition first:** try `kOmegaSSTLM` on the Re 3e5 designs against XFoil; without it T2 is not a credible
  terminal fidelity for the hard preset.
- Part 2: recovery ladder L1-L5 on `SolverOverrides` / re-mesh, classification by the monitor's signature,
  `RecoveryAction` schema and the CFD agent (LLM chooses the level; code forbids repeats, bounds the ladder).
- Part 3: mesh-independence study (n_surface, first cell, growth, far field), then wiring `of2d` into the graph
  for top candidates (promotion from XFoil, fidelity-gap handling, validator checks for residuals / mesh / y+).
- Then benchmark 4 on the finished system.

## Session 14, continued: milestone 3, the vision Critic and its evaluation

PR #11 (milestone 2) was merged before the two doc commits that followed it; the branch was rebased onto main
with them.

### Images (`swarm/critic/render.py`)
Three deterministic images per Critic call: fixed axes and ranges, candidate solid over parent dashed, key
numbers in the title. BLUEPRINT's four images (Cp, residuals, contour, streamlines) are OpenFOAM's; at T0/T1:
- `cp`: -Cp(x/c) on both surfaces;
- `boundary_layer`: suction-side H with the screen's limit, and Cf at XFoil (reversed flow shaded);
- `section`: the section in the car frame with the rulebook's lines (placeholder car).
Surface data from XFoil's BL dump (Cp = 1 - Ue²) or one NeuralFoil call (32 stations). About 0.4 s and
~500 input tokens per image.

### Wiring
- `LLMClient.structured(..., images={name: path})`; `AnthropicClient` sends a text label and a base64 PNG per
  image after the brief; traces keep paths and hashes, not bytes. Clients declare `sees_images`; the graph
  renders only for those (the rule-based mock cannot see, so mock runs render nothing and stay fast).
- Critic prompt: an image paragraph when vision is on, "No images in this run" otherwise; `Finding.source`
  may be "section"; `merge_verdict` unchanged (a fatal finding vetoes; nothing rescues a failed check).
  `EvalRecord.critic_images` records what the Critic was shown; event `critic_render_failed` if rendering
  fails (the Critic still runs on the numbers).
- `run(vision=True)` / `--no-vision`; meta.json `vision`. **Vision is on by default**, so the LLM benchmark
  arms will use it (about $0.25 more per 40-evaluation run).

### Critic failure zoo (`swarm/evals/critic_zoo.py`, `scripts/critic_eval.py`, `evals/critic_zoo.json`, `docs/CRITIC_EVAL.md`)
26 labelled cases (11 trust: clean XFoil / NeuralFoil near the target, separated-but-converged; 15 flag:
40-panel solves, wrong solution branch, Cl/Cd scaled by 0.6, stale images, a suction-side bump, sign flip,
Cd / 5), each with the parent and (XFoil) the same design's NeuralFoil record, as a run would have. Cached as
surface data; images re-rendered. Arms: numeric (validators only), llm_text, llm_vision; hard flag = NON_PHYSICAL
/ NUMERICAL_FAILURE or a fatal finding, soft adds a fidelity-gap / confidence doubt or a suspect finding marked
inconsistent with the numbers (design checks such as TE separation do not count).
- Numeric arm (offline): hard precision 100% (3/3), recall 20% (3/15); soft 100% / 53%.
- 7 bad cases are invisible to every numeric check (coarse panels, stale images, surface kink): what vision
  must add.
- **LLM arms run (API working again; `claude-sonnet-5` via AEROSWARM_MODEL; $0.33 text, $0.48 vision, one pass):
  vision added nothing.** Hard recall numeric 3/15, text 4/15, vision 3/15; soft 8/15 in all; no false alarms.
  The vision Critic saw the kink ("small spike near x/c 0.28–0.3") and called it a bubble; read the scaled
  case's unchanged Cp as "matching the large Cl deficit"; called the stale Cp "consistent" with the printed Cl.
  It describes the plots in terms of the stated numbers instead of checking the numbers against them.

### Tests
`tests/test_vision.py` (10: rendering, request payload and trace, graph wiring with an image-capable mock,
--no-vision, veto/no-rescue) and `tests/test_critic_zoo.py` (6: committed cases, numeric arm reproduces the
committed results, images only in the vision arm via a scripted client, errors not scored, doc regenerated).

### After the evaluation (user: "yes" to both proposals)
- **Vision off by default**: `run(vision=False)`, CLI `--vision` (was `--no-vision`). The benchmark's LLM arms
  therefore run without images.
- **Two deterministic surface checks** in the numeric validator (`swarm/critic/surface.py`; `ValidatorConfig`
  `cp_integral_tol_*`, `cp_spike_max`), fed by the graph, `baselines.record_evaluation` (baselines and the inner
  optimizer) and the Critic zoo; `baselines.random_start` is unchanged, so the seeded starts are identical.
  - `cp_integral`: Cl integrated from the solver's surface Cp vs the reported Cl (XFoil 0.02 + 1%, NeuralFoil
    0.05 + 12%); fatal.
  - `cp_smoothness` (XFoil): no narrow (< 0.04 c) suction-side -Cp spike above 0.15; fatal.
  - Calibrated on 59 + 118 random XFoil designs and 300 NeuralFoil designs; never fired on the 263 converged
    XFoil zoo solutions or the 60 offline benchmark-4 runs (re-run: outcomes unchanged).
- Critic zoo, numeric arm: hard recall 3/15 → **10/15**, precision 100%. Still missed: coarse panels (3), wrong
  branch (2): converged, self-consistent solutions; catching them needs a second solve.

### Next (waiting for the user)
- The benchmark LLM arms (hybrid seed 33, then `--methods hybrid llm --parallel 5`): the API works again.

## Session 14 (2026-10-15): milestone 2 finished: failure zoo, recovery statistics, sign scoring

Main was 6 commits behind `claude/intelligent-hopper-xn7qea` (session 13's last commits); the user merged them
(PR #10) first. Milestone 2 had the XFoil ladder (sessions 1–3) but not the zoo or the metrics. Done now, all
offline, in `swarm/evals/`:

### Recovery-ladder statistics (`swarm/evals/recovery.py`)
From the ledger only: design-point XFoil solves by the level that produced them (a result at level k means
L0..k-1 failed), exhausted ladders (NeuralFoil fallback with `fallback_from="xfoil"`), and stall-probe points
(`stall_margin.levels`, `None` = exhausted). Recovery rate = recovered / L0 failures. New "XFoil recovery ladder"
section in every run report.

### CAD sign-prediction scoring (`swarm/evals/signs.py`)
Each proposal's predicted ΔCl/ΔCd signs (race-car Cl) against its result minus its parent's, same fidelity,
deadband ±0.002 Cl / ±0.0001 Cd (a 0 prediction is right only inside it). A record is scored on its joint
prediction (all changes agree); opposite predictions are "mixed", not scored. Per parameter: single-change
proposals and the implied sensitivity sign (prediction × sign of the parameter change), which shows a
parameter argued both ways. New "CAD sign predictions" report section. The committed example LLM run
(`runs/examples/hard_llm_…`): Cl 11/11, Cd 10/10 joint predictions right, 7 mixed; implied dCl/dalpha
negative in all 17 alpha changes; thickness argued both ways (1 / 10).

### Benchmark
`scripts/benchmark.py report` has a new table per method: XFoil solves (design + probe), recovered, exhausted,
CAD Cl/Cd sign accuracy. Smoke-tested on one mock and one random seed (not in docs/BENCHMARK4.md: that doc is
regenerated from runs/bench4, which this session does not have).

### XFoil failure zoo (`swarm/evals/zoo.py`, `scripts/failure_zoo.py`, `evals/xfoil_zoo.json`, `docs/FAILURE_ZOO.md`)
78 cases in 6 labelled categories (thin sections at high alpha, FSAE-legal near/past Cl,max, aft camber, thick at
high alpha, and two controls: the target region and low alpha), hard preset Re 3e5, rulebook check off. Every
case is solved at every level, so the zoo measures both recovery and whether converged levels agree ("branch":
same panel count, another solution; "panels": L3's 240 panels against 160). Run: 164 s with 3 processes.
- 14 L0 failures: 7 recovered, 7 exhausted. All 7 exhausted cases are t 0.08 (FSAE-illegal).
- FSAE-legal (46 cases): 4 L0 failures, all recovered (L1, L2, L3, L3), within 0.003–0.027 of NeuralFoil.
- Wrong branch accepted on 2 thin cases at α 14: L0/L1 converge on a low-lift solution, 0.10–0.15 below what
  continuation and NeuralFoil give; the ladder stops at the first converged level.
- **Panel count:** at 160 panels (L0–L2) the target region has 0.010–0.021 less downforce than at 400 panels
  (median 0.016; separate check of 9 designs, table in FAILURE_ZOO.md), against the ±0.03 tolerance. The
  under-loaded XFoil results of benchmark 4 and the pilot (−1.785 to −1.798, edge −1.80) are within that bias.
  The target, gated sweep and screen were all derived at 160 panels, so they agree with each other; not changed.

### Tests
`tests/test_evals.py` (11): ladder statistics on synthetic ledgers and in mock graph runs (L2 recovery,
exhausted ladder), sign scoring (joint/mixed/deadband/no parent/other fidelity/quarantined), zoo outcomes on a
fake solver, and the committed cache (matches the case list, counts add up, the doc is regenerated from it).

### Next (waiting for the user)
- **Panel count: decided, keep 160** (user, 2026-10-15). Measured against 320 on the 46 FSAE-legal zoo cases
  at L0: 320 converged 44 vs 42, ~0.26 s vs ~0.05 s per solve, Cl 0.006–0.022 more downforce in the target
  region (320 is within 0.004 of 400). Results stay consistent with the target, gated sweep and screen (all at
  160); a reported Cl is "XFoil at 160 panels" and carries a ~0.016 under-prediction of downforce.
- Optional: a ladder that does not stop at the first converged level above some alpha (e.g. also run L2 and
  take continuation when they disagree). No FSAE-legal zoo case needs it; it only matters at the domain edge.
- LLM runs still wait on the API usage limit (resets 2026-11-01): hybrid seed 33, then the full arms.
- Deferred by the user ("later"): FSAE rules not checked in 2D (T.7.6 width / T.7.3.3 inboard of the rear
  tires, T.7.1.4's 3 mm vertical-edge radius on end plates, V.1.1 wheel keep-out) need a span parameter,
  end-plate geometry and wheel positions; and `PLACEHOLDER_CAR` should be replaced with the team's car numbers.
- Milestone 3 (vision Critic) is next in the build order. The Critic's own failure zoo (leaky STL, wrong Aref,
  coarse mesh; BLUEPRINT §3) belongs with OpenFOAM (milestone 5).

### Known issues
- XFoil at 160 panels under-predicts downforce by ~0.016 in the target region (kept by decision; see Next).
- CMA-ES (BLUEPRINT §3) is not implemented; TPE only.

## Session 13 (2026-10-06): milestone 4, the hybrid inner optimizer; offline benchmark 4

Session 12 (FSAE 2027) was on `claude/loving-turing-kld1sk`, not on main; this branch fast-forwarded to it first.

### Inner optimizer (`swarm/optim/inner_loop.py`, graph node `inner_optimize`)
When the Chief's memo sets `mode="inner_optimizer"` (and the run allows it), the graph skips the CAD agent and the
Critic for that generation and runs Optuna TPE (seeded from the parent cid and the generation; 3 start-up trials,
multivariate) for `inner_budget` evaluations:
- search space: the memo's focus_params only, within the trust region around the selected parent
  (`explore.current_parent`, as for a CAD step), one-sided for a "+"/"-" direction; other parameters stay at the
  parent's values; the box lies on the 1e-4 parameter grid and main_thickness starts at the rulebook's LE-radius
  minimum; an interval narrower than 2e-4 is dropped;
- warm start: every NeuralFoil ledger record in the searched subspace (focus parameters in the box, every other
  parameter equal to the parent's) is added as a trial;
- objective `baselines.tpe_value` (constraint violation, objective as a tie-break), as in the Optuna baseline;
- each evaluation goes through `baselines.record_evaluation` (renamed from `_record`): geometry/rulebook checks,
  NeuralFoil, the numeric validator, the NeuralFoil screen; numeric verdict, no LLM call in the loop;
- geometry-infeasible and near-duplicate proposals (`cad.apply.near_duplicate`) cost no evaluation; after 60 such
  proposals the run stops; an exception while evaluating stops the run and keeps the records already made
  (`inner_optimizer_error`);
- every evaluation is a ledger record (`EvalRecord.inner_optimizer=True`, generation = the memo's, parent_cid = the
  parent) and counts toward max_evals; the run's last evaluation is never an inner one (`INNER_RESERVE = 1`:
  the budget is clipped, and sanitize refuses the mode with one evaluation left), so it can go to a promotion;
- events `inner_optimizer_started`, `inner_trial`, `inner_optimizer_finished` (summary: box, warm trials, evals, why
  it stopped, best design with Cl/Cd/violation/screen, designs in the box, promotable designs);
- an inner run that evaluates nothing (empty box, all repeats, no evaluations left) falls back to a reasoned CAD
  step in the same generation (`inner_optimizer_empty`).

### Chief
- `chief.sanitize`: the mode is honoured when state `inner_allowed` is true (`run(inner_optimizer=True)` default;
  `--no-inner-optimizer` / `inner_optimizer=False` coerce it to reasoned_step, `inner_optimizer_unavailable`); a
  promotion that goes ahead takes precedence (`inner_optimizer_deferred`); `inner_budget` clamped to 3–12, 0 = 8
  (`inner_budget_coerced`); fidelity forced to neuralfoil (`inner_optimizer_fidelity`); an inner_budget on a
  reasoned_step memo is dropped with `inner_budget_ignored`. A failed Chief call never reuses an inner memo.
- Prompt: the mode paragraph is filled per run (`briefs.mode_text`): both modes described generically when
  allowed, "disabled in this run" otherwise; the LLM-only prompt and brief do not mention inner runs. No
  task-specific hints. `--resume` refuses `--no-inner-optimizer` (the setting is fixed at run start).
- Brief: "Inner-optimizer runs" section (last 3 summaries, ledger numbers), the history outcome of an inner
  generation is its summary, a `by` column (agents / inner) in the ledger tables, the Critic's verdict is labelled
  with the last agent-evaluated record. Report: an "Inner-optimizer runs" section and a `by` column.
- `MockClient(inner_budget=K)`: after 2 generations without improvement it uses the mode (alternating with
  reasoned steps); the default mock (K = 0) is unchanged.

### Other changes
- **`ledger.violation` counted NeuralFoil separation only at the design alpha.** The screen's alpha+1/+2 TE-H
  warning (`probe_sep`, the analogue of XFoil's probe-range separation, which was counted) was ignored, so a
  design the screen failed on it scored zero violation. Found in the first smoke run: every inner run's "best"
  was such a design. Now counted; this changes parent selection (all graph runs) and the Optuna baseline's
  objective. The screen itself is unchanged.
- `ledger.no_improve_streak` takes each generation's best record (it took the first record of a generation).

### Spec review (subagent) and fixes
A review of the milestone against the spec found:
- **A crash in the warm start** (blocker): a ledger design exactly on the trust-region edge passed the region
  check, but Optuna's distribution rejected it (6.0 − 0.3·16 = 1.2000000000000002 in floats). 11 inner runs in
  the first mock_hybrid pass crashed this way (seeds 88: 4, 165: 4, 143: 3), each a wasted generation and a node
  error (5 make a run fatal); the first write-up counted only the 52 runs that finished. Fixed (grid box, clipping),
  regression test; mock_hybrid re-run: no crash.
- About 20% of warm-start trials (141 of 715) were designs that differed from the parent off the focus
  parameters, read by TPE as if at the parent's values: warm start now takes the exact subspace only.
- Records already evaluated were dropped if the node raised mid-run: now kept.
- The benchmark appended to existing run directories on a re-run (paying again, mixing two runs): it now skips
  finished and unfinished directories.
- Doc numbers: mock_hybrid used 584 evaluations (not 600) in that pass; the mock plateaus came at 32–37.
- Not changed: the one-sided box for "+"/"-" directions (the review found it a reasonable reading); dial coverage
  counts inner records as moves (they are designs that differ from their parent); the report's inner section
  prints the run summaries (their numbers come from the records); Optuna stays `>=5.0.0` (the lock pins 5.0.0).

### Benchmark 4 (`scripts/benchmark.py`, `runs/bench4/` not committed, `docs/BENCHMARK4.md`)
Arms: hybrid (real LLM, inner optimizer allowed), llm (real LLM, disabled), mock, mock_hybrid (MockClient with
inner_budget 8; an offline check of the hybrid path, NOT an LLM), random, optuna. 15 seeds, 40 evaluations, starts
from `random_start` under FSAE 2027. Offline arms (mock_hybrid after the review fixes):

| method | success | 95% (Wilson) | evals to target | XFoil evals / run |
|---|---|---|---|---|
| mock | 1/15 (s154) | 1–30% | 25 | 0.1 |
| mock_hybrid | 2/15 (s99 found by an inner run; s154 by a reasoned step) | 4–38% | 38, 25 | 0.3 |
| random | 0/15 | 0–20% | — | 0 |
| optuna | 1/15 (s77) | 1–30% | 19 | 0.5 |

- mock_hybrid: 55 inner runs, none crashed, 371 of 583 evaluations; warm starts 2–33 designs (mean 9.7); 26
  improved on the base's value; 62 inner designs in the box at NeuralFoil, 5 screen-passed, 3 promoted: 1 passed
  XFoil, 2 came back under-loaded (XFoil Cl −1.785, −1.788).
- Budgets differ: mock declared a plateau in 13 of 15 runs (10 at 32 evaluations, the rest at 34–37); mock_hybrid
  never did. Not a budget-matched comparison. The intervals overlap; the offline arms do not separate.
- Offline arms take seconds per run.

### Hybrid pilot (real LLM, `claude-sonnet-5` via AEROSWARM_MODEL; seeds 33, 99, 154; `runs/bench4/hybrid_s*`)
| seed | termination | evals (inner) | inner runs | XFoil evals | est. cost | LLM calls |
|---|---|---|---|---|---|---|
| 99 | eval_budget | 40 (32) | 4 | 4 | $0.61 | 24 |
| 154 | eval_budget | 40 (32) | 4 | 2 | $0.68 | 27 |
| 33 | plateau at 39, labelled invalid_llm (see below) | 39 (36) | 5 | 2 | $0.26 | 12 |

- No target met. The Chief chose the inner optimizer readily: 13 inner runs, almost always K = 8, 100 of 119
  evaluations. Inner runs put 14 designs in the target box at NeuralFoil but only 1 passed the screen.
- 8 XFoil evaluations, 7 of inner-found designs. All failed: 7 outside the box (Cl −1.786 to −1.798 on seeds 33 and
  99, −1.861 and −1.868 on seed 154), 1 failed the stall probe. The Chief spent both screen overrides in every run by
  gen 5; all 6 failed at XFoil.
- Where the misses come from (per design, `briefs.xfoil_record` on the pilot ledgers): the 6 overridden designs were
  inside the box at NeuralFoil and moved by 0.013–0.046 at XFoil (+0.015 on seed 33, −0.041 and −0.046 on seed 154,
  ±0.0135 on seed 99). The 2 screen-passed promotions (seed 99) agreed with NeuralFoil within 0.003 but sat at or
  outside the box edge already at NeuralFoil (Cl −1.8002, −1.7846: the 2·tol promotion window). The first write-up
  of this pilot said screen-passed in-box designs came back 0.03–0.04 off; that was wrong.
- Cost: $0.26–0.68 per run (inner generations make no CAD or Critic call), against ~$2.5–3 per LLM-only run under
  Formula Student 2026 (session 11).
- Seed 33 never asked for a CAD step (only inner runs and promotions), so the CAD agent was never called and the
  every-agent validity rule marked the run invalid_llm. Fixed: the CAD agent is exempt when inner-optimizer runs
  took the place of every CAD step (`LLMHealth.check(not_needed=...)`); a CAD agent called and never successful
  still invalidates. That run is in `runs/bench4_aborted/hybrid_s33_cad_rule/`.
- The re-run of seed 33 hit the account's API limit at its 9th generation ("You have reached your specified API
  usage limits. You will regain access on 2026-11-01 at 00:00 UTC"): `runs/bench4_aborted/hybrid_s33_usage_limit/`.
  The batch guard did not match that wording; it does now ("usage limit"). Pilot spend about $1.83 (estimated).

### Next (waiting for the user)
- The API usage limit must be raised (or wait for 2026-11-01) before any further LLM run.
- Then: re-run hybrid seed 33, decide on the full arms (`--methods hybrid llm --parallel 5`; a re-run skips
  finished seeds). From the pilot a hybrid arm costs about $5–10; the llm arm about $40–45 (user's estimate).
- Pilot pattern: the inner runs find in-box designs that fail the screen; the Chief overrides early and every
  override fails (as in session 11), each moving 0.013–0.046 in Cl at XFoil; screen-passed promotions agreed with
  NeuralFoil but were at the box edge or in the 2·tol window only.

### Offline experiments after the pilot (user: "try the changes first and test them offline")
- **Graded separation in `ledger.violation` (tried, reverted).** NeuralFoil separation cost 0.1 plus the relative
  excess of the screen's TE H over its limit (at most 1) instead of 1. Offline arms with it
  (`runs/bench4_graded/`, not committed) against `runs/bench4/`:

  | arm | successes (old → graded) | in-box, screen-ok designs | in the 2·tol window, screen-ok |
  |---|---|---|---|
  | mock | 1 → 0 | 2 → 1 | 5 → 2 |
  | mock_hybrid | 2 → 0 | 2 → 2 | 6 → 10 |
  | optuna | 1 → 1 | 2 → 3 | 9 → 7 |
  | random (does not use the score) | 0 → 0, identical ledgers | | |

  No improvement: in-box designs that pass the screen stay rare whichever score guides the search. Reverted.
- **Kept: the Chief brief lists every design evaluated at XFoil** (`briefs.xfoil_record`): found by inner/agents,
  route (screen passed / screen override), NeuralFoil Cl and whether it was in the box, XFoil Cl, dcl = XFoil −
  NeuralFoil, XFoil Cd, outcome, and per route how many were in the box at NeuralFoil and how many passed. Ledger
  numbers only, no advice; shown in both LLM arms. It cannot be measured offline (the mock reads facts, not prose);
  only a real-LLM run shows whether it changes promotions.

### Known issues
- The violation's separation term is binary (0/1), so TPE gets no gradient toward fixing a screen separation
  warning; a graded term (TE H over the limit) would be the next thing to try, but it changes parent selection.
- Fixed: the batch runner stops on the first API account error (credit, key, billing; `benchmark.account_error`),
  exit code 2, and moves that seed's run to `<root>_aborted/` so a re-run starts it again. Runs killed in flight
  by the stop leave unfinished directories, which a re-run skips until they are moved or deleted.
- CMA-ES (BLUEPRINT §3 mentions it) is not implemented; TPE only.
- `run(inner_optimizer=True)` is the default, so plain CLI LLM runs may use the mode.

## Session 12 (2026-10-06): rulebook switched to FSAE 2027

### Rule check of the old setup (online, before the switch)
- NACA 4-digit geometry matches the standard equations (coefficients, camber line, LE radius
  1.1019 t²c); with our blunt-TE addition off it equals AeroSandbox's generator to ~1e-16 c.
  Deliberate departures: a blunt TE (+0.7% c, 2.7–2.9 mm) and non-integer "digits".
- Formula Student 2026 limits in the code (1100 / 500 mm heights, 250 mm overhang, 30 mm clearance,
  3 / 1 mm edge radii) match search excerpts of FS-Rules 2026; formulastudent.de is blocked by the
  environment's network policy, so the PDF itself was not read (rule numbers T8.2.3 and T2.2.1
  unconfirmed).
- The user added `docs/FSAE_Rules_2027_V1.pdf` (Formula SAE Rules 2027 v1.0) and chose it.

### FSAE 2027 v1.0 (`swarm/cad/regulations.py`; default `DesignSpec.rulebook`)
| Rule | Limit | Formula Student 2026 (still selectable) |
|---|---|---|
| T.7.7.1a | no higher than 1200 mm in the Rear Aerodynamic Zone | lower than 1100 mm |
| T.7.7.1b | no higher than 500 mm outside it | lower than 500 mm |
| T.7.5b | no more than 250 mm rearward of the rear tires | 250 mm |
| T.7.1.4 | 5 mm radius on forward facing horizontal edges: **t ≥ 0.123** on 300 mm | 3 mm: t ≥ 0.0953 |
| T.7.1.5 | other edges not sharp (project threshold 1 mm radius, 2 mm TE) | 1 mm |
| V.1.4.1 | no ground contact (no fixed number) | 30 mm |

Not checked (2D): width T.7.6 / Rear Aerodynamic Zone laterally, end plates (3 mm vertical edges),
V.1.1 wheel keep-out. The car is still `PLACEHOLDER_CAR`.

### What moved
- Starts: default and hard presets now t 0.13 (were 0.12 / 0.10, both FSAE-illegal). Hard start:
  NeuralFoil Cl −1.546, Cd 0.0168, screen failed; XFoil Cl −1.540.
- Gated sweep extended to t 0.125, 0.13, 0.14, 0.145 (196 geometries, 8,036 points; 1 failed).
  FSAE-legal grid: gated Cl_max 1.985. **Target kept at −1.83 ± 0.03, Cd ≤ 0.025**: 42 passing grid
  points in the box, 18 interior (camber < 0.09, t > 0.125), **all 42 pass cold** through the
  pipeline (ladder, screen-independent XFoil gate, stall probe). The strict "hardest box with ≥ 10
  interior points" rule would give −1.84 (13 interior); −1.85 has 5.
- Witness: m 0.085, p 0.35, t 0.135, α 8.75 (NeuralFoil Cl −1.8093, screen ok 0.056; XFoil
  Cl −1.8241, Cd 0.02251, margin 0.082). The FS witness (t 0.12) is FSAE-illegal.
- All 7 XFoil winners so far are FSAE-legal (t 0.130–0.1365, LE radius 5.6–6.2 mm); none used a
  thickness below 0.123 even when Formula Student allowed it.
- Screen on the FSAE-legal window (937 points, 84 XFoil-feasible): the current rule (slope ≥ 0.055,
  H < 4.35) gives 17/88 false passes (19.3%), 13/84 blocked (15.5%; was 10.1%); it is still the
  best in the 15–20% band, so unchanged. The FP + 3·FB cross-check now prefers slope ≥ 0.0525,
  H < 4.55 (30.8% / 3.6%).
- Tests run on FSAE (test start t 0.13); the session-2 XFoil regression keeps FS 2026.

### Consequences / next
- All benchmark results so far (bench v1, v2, the session-11 pilot) are under Formula Student
  2026; the seeded starts change under FSAE (`random_start` rejects t < 0.123). A comparison under
  FSAE needs fresh runs of every method (offline ones are minutes; LLM ~$2.5–3 per run).
- Target decision (user): **keep −1.83 ± 0.03, Cd ≤ 0.025** under FSAE (same target as the earlier
  benchmarks; −1.84 would be the strict-rule choice). Screen: unchanged unless the user decides otherwise.

## Session 11 (2026-10-05): screen-override limits, stall_untested, findings, 3-seed pilot

### Screen overrides (`swarm/overrides.py`)
- At most **2 per run** (promotions and direct-to-XFoil designs together), and only for a design whose
  **NeuralFoil result is inside the target box** (|Cl − target| ≤ tol, Cd ≤ cd_max), not merely in the
  2·tol promotion window. A refused override is logged (`screen_override_refused`, with why) and the
  design stays at NeuralFoil. A direct-to-XFoil design is always screened; an override is spent only
  if the screen fails.
- Every Chief brief shows the **track record**: "Used k of 2", each override and what XFoil found;
  the blocked list says which candidates are override-eligible. The run report has a "Screen
  overrides" section. Prompt updated.

### stall_untested
`EvalRecord.stall_untested` (computed, written to ledger.jsonl): an XFoil result whose stall probe did
not run (it runs only for a design that clears every other check). Shown in the report's ledger
table, a `stall_probe` column in the Chief's tables, the Chief's history and the override track
record. Excluded from evidence about the screen: `compare_with_xfoil` compares nothing without the
probe (no `screen_xfoil_disagreement`), and the report lists such results as "not evidence".

### docs/FINDINGS.md
- F1 (pre-fix, benchmark v2): 24 of 26 XFoil evaluations were overrides, 0 passed. The probe ran on 3
  (all failed, as the screen said); 21 are stall untested. Three quoted reasons from traces, checked
  against the ledger: the "screen over-flags" argument cites earlier overridden designs whose probe
  never ran. Session 10's "15 failed on what the screen flagged" counted 12 such results; corrected
  in BENCHMARK.md and session 10 below.
- F2: the pilot below.

### Pilot with the fix (seeds 44, 33, 55; `runs/bench3/`, not committed)
| seed | result | evals | est. cost | overrides used | passed XFoil |
|---|---|---|---|---|---|
| 44 | no pass (plateau at 33) | 33 | $2.45 | 2 | 0 |
| 33 | target met | 30 | $2.45 | 2 | 0 |
| 55 | target met | 35 | $2.98 | 2 | 0 |

The Chief spent both overrides in every run by generation 9 and none passed (probe ran on 1, failed;
5 stall untested); no refusals. Both successes were screen-passed promotions at generations 29 and 34.
Seed 44 (pre-fix win at 19 evals) did not succeed; one sample per seed, so this says nothing either way
about the fix. The stall_untested label did not stop the Chief citing an untested result as a screen
false positive; the cap bounded the cost.

### Next (waiting for the user)
- Decide on the remaining 12 LLM seeds (11, 22, 66, 77, 88, 99, 110, 121, 132, 143, 154, 165) at about
  $2.5–3 each: `uv run python scripts/benchmark.py run --methods llm --parallel 5 --root runs/bench3
  --seeds ...`. The pre-fix LLM runs (bench2) should not be mixed with post-fix ones; the offline
  methods in `runs/bench2/` are unaffected by this change (the baselines never override, and
  stall_untested only labels).
- `cmd_report` reads one root; reporting bench3 LLM with bench2 offline needs a second root option.

## Session 10 (2026-10-03): cost-weighted screen, plateau policy, dial coverage, Optuna, benchmark v2

### NeuralFoil screen re-tuned for cost, not ≤ 5% false passes (`scripts/calibrate_screen_rules.py`)
A false pass costs one XFoil evaluation; a false block can lose the feasible design. Criterion now:
15–20% false passes in the promotion window with the fewest blocks; a cost FP + w·FB cross-check.
Same data as session 9 (gated sweep, 804 window points, 69 pass XFoil's gate).

| rule (window) | false pass | blocks |
|---|---|---|
| session 6: slope ≥ 0.05 | 50/118 (42.4%) | 1/69 (1.4%) |
| session 9: slope ≥ 0.0575, H(α+1, α+2) < 3.85 | 2/41 (4.9%) | 30/69 (43%) |
| (a) slope only | no setting in 15–20% (0.060: 25.0% / 34.8%; 0.065: 10.0% / 60.9%) | |
| (b) α+3 probe, best in band: ≥ 0.050 | 6/30 (20.0%) | 45/69 (65.2%) |
| (c), (c') knee | no setting in 15–20% | |
| **(d) slope ≥ 0.055, H(α+1, α+2) < 4.35 (new)** | **13/75 (17.3%)** | **7/69 (10.1%)** |
| cost FP + 3·FB, family (d) | same as the new rule | |
| cost FP + 5·FB or 10·FB, family (d): ≥ 0.050, H < 4.55 | 39/107 (36.4%) | 1/69 (1.4%) |

- All 8,085 points: 165/3,158 false passes (5.2%), 122/3,115 blocks (3.9%). 2-fold split by geometry,
  held out: 9.1% / 9.1% and 28.9% / 11.1% (false pass / blocks).
- Live run 2's winner `abb9803ead` passes (slope 0.0589, H 3.22 / 3.57 / 4.12), as do benchmark v1's
  winner `1449e37232` and the witness; `tests/test_screen.py` pins all three.
- **screen_override for promotions**: the Chief may promote a screen-failed design by setting
  `screen_override` to a reason (event `promotion_screen_override`, reason logged); without one the
  promotion is still blocked. XFoil stays authoritative.

### Plateau: no plateau termination before 80% of the budget (`swarm/explore.py`)
`declare_plateau` ends the run only once `ceil(0.8·max_evals)` evaluations are used (32 of 40). Earlier
it becomes exploration, alternating (event `plateau_deferred`, in the Chief's history and the report):
- widen: trust radius ≥ 0.3 (or doubled), focus padded with the other free parameters, directions kept;
- restart: the CAD base moves to the least-violating design ≥ 0.2 of the range (L∞) from the current
  base and earlier anchors (else the farthest), directions free, radius ≥ 0.15; for 3 generations the
  parent is the best design of that branch (anchor + designs first evaluated since), then normal
  parent selection resumes. With a promotion in the same memo, the promotion is the move.

### Chief brief: dial coverage (`ledger.dial_coverage`)
Per free parameter: bounds, range explored over all evaluated designs (and share of the bounds),
moves (designs whose value differs from their parent's; up/down; promotions are not moves), last
move (generation, from → to). No task-specific hints.

### Optuna TPE baseline (`baselines.search("optuna")`, optuna 5.0)
Same loop as random search (shared `baselines.search`): geometry checks, NeuralFoil screen, the
promotion rule, XFoil ladder, stall probe, validator, 40 evaluations. TPE (seeded, Optuna defaults,
10 random start-up trials) minimizes `ledger.violation` (objective as a tie-break); the start is its
first trial; XFoil results of promoted designs are added as trials; geometry-infeasible proposals cost
no evaluation (told to TPE as a penalty of 1000). Random search's sample sequence is unchanged.
`swarm/stats.py`: Wilson interval, quartiles.

### Benchmark v2 (`docs/BENCHMARK.md`; runs in `runs/bench2/`, not committed) — LLM arm incomplete
15 seeds (11, 22, …, 165), 40 evaluations, $4 / 1.5 h safety caps.

| method | seeds completed | success | 95% (Wilson) | evals to target | XFoil evals / run |
|---|---|---|---|---|---|
| LLM | **1/15** | 1/1 | 21–100% | 19 | 5 |
| mock | 15/15 | 0/15 | 0–20% | — | 0 |
| random | 15/15 | 0/15 | 0–20% | — | 0 |
| Optuna TPE | 15/15 | 2/15 (13%) | 4–38% | 24, 33 | 0.2 |

- **The Anthropic API credit ran out 24 minutes into the LLM batch** ("credit balance is too low").
  Seed 44 finished (target met at 19 evals, $1.22). Five runs aborted mid-run as `invalid_llm` at
  14–28 evaluations (none had met the target; $9.07 between them) and nine at their first call. The
  14 are excluded from the table and kept in `runs/bench2_aborted/`. Total LLM spend $10.29 (estimated).
- In the six LLM runs, **the Chief overrode the screen on 24 of 26 XFoil evaluations; none of the 24
  passed XFoil**. The stall probe ran on 3 (all failed, as the screen said); 21 are stall untested.
  (This entry first said "15 failed on what the screen flagged": that counted 12 results with TE
  separation at alpha whose stall probe never ran; see session 11.) The winner was a screen-passed
  promotion.
- No run stopped on a safety cap. No LLM run declared a plateau before it ended.

### Known issues / next
- **Finish the LLM arm** once the API credit is topped up (14 seeds; ~$3 per full run, ≤ $4 cap):
  `uv run python scripts/benchmark.py run --methods llm --parallel 5 --seeds 11 22 33 55 66 77 88 99 110 121 132 143 154 165`,
  then `uv run python scripts/benchmark.py report`.
- The batch runner keeps starting runs after the API refuses on credit (each fails in ~1 s, no cost);
  it could stop the batch on the first such error.
- screen_override is used almost by default and was 0/24. Options (not implemented): show the run's
  override track record in the Chief brief; mark XFoil results whose stall probe did not run as
  "stall untested" (the Chief read box-failed XFoil runs as proof the screen over-flags).
- NeuralFoil reads near-target designs more loaded than XFoil (9 promotions at NeuralFoil within 2·tol
  came back at Cl −1.73 to −1.80).

## Session 9 (2026-10-02): screen recalibration, loop guards, example run, benchmark

### NeuralFoil screen recalibrated (`scripts/calibrate_screen_rules.py` on the gated sweep)
Ground truth: XFoil's full stall gate (margin ≥ 0.05, no TE separation at α+1/+2). Population that
matters: the promotion window (NeuralFoil Cl within 2·tol of −1.83, NeuralFoil Cd ≤ 0.025): 804 sweep
points, 69 of them pass XFoil. "false pass" = screen passes that fail XFoil; "blocks" = XFoil passes
the screen rejects.

| rule | window: false pass | window: blocks | all 8,085: false pass | all: blocks |
|---|---|---|---|---|
| session 6: slope ≥ 0.05 | 50/118 (42%) | 1/69 (1%) | 11.6% | 0.9% |
| (a) slope only, best ≤ 5% FP: ≥ 0.075 | 0/1 | 68/69 (99%) | — | — |
| (b) α+3 probe, min of 3 slopes | never ≤ 5% (best 16.7%) | | 3.7% @ 0.045 | 11.8% |
| (c) knee: slope ≥ 0.05 and s1−s2 ≤ X | never ≤ 5% | | 4.5% @ X 0.013 | 25.6% |
| **(d) slope ≥ 0.0575 and TE H < 3.85 at α+1, α+2** | **2/41 (4.9%)** | **30/69 (43%)** | **2.7%** | **10.3%** |

- The session-6 calibration (27/38 caught, 0/25 blocked "near the target") used the old grid and an
  XFoil-defined near-target set; in the window the screen actually gates, it was 42% false passes.
- 22 of the 50 old false passes failed XFoil only on separation at the probes; NeuralFoil's TE shape
  factor at α+2 is higher for them (median 4.19 vs 3.79). (b) and (c) cannot fix that; (d) does.
- Robustness: neighbouring settings give 5–7% false passes; a 2-fold split by geometry gives 6–7%
  held-out false passes with 31–55% blocks. ~5% is reachable only by blocking a large share of
  feasible designs.
- **Cost seen on real data**: replayed on live run 2's four promotions, (d) blocks the three XFoil
  rejected and also the winner (`abb9803ead`: H 4.12 at α+2, XFoil attached).
- Implemented: `ValidatorConfig.screen_min_dcl_dalpha = 0.0575`, `screen_h_probe_max = 3.85`;
  `SurrogateScreen.probe_sep` / `margin_ok`. XFoil's 0.05 is unchanged.

### Loop guards
- **Near-duplicates** (`cad.apply.near_duplicate`): a proposal within α 0.05°, camber / position /
  thickness 0.002 (others exact) of a design evaluated at the same fidelity is rejected like an
  exact duplicate, naming that design and its result. The deterministic fallback avoids them too.
- **Chief/CAD deadlock**: after a `chief_cad_disagreement` the Chief's next brief lists it; each such
  parameter kept in focus must adopt the CAD's direction or be `locked` (the CAD tool rejects any
  move against a locked direction, reason or not). A restated direction without a lock becomes a
  lock, "free" adopts the CAD's direction (`deadlock_coerced`).
- Report: the blocked list (report and Chief brief) is sorted by generation; stall-plot slope labels
  sit on the side of their segment away from the threshold line.
- Evolution strip: the "most instructive failure" frame is the start design only when nothing else
  failed. Benchmark run `llm_s44` showed the start as both "before" and "middle" (it had the run's
  worst screen slope); its strip, GIF and stall plot in `runs/bench/llm_s44/` were re-rendered.

### Example run committed
`runs/examples/hard_llm_20261001-201455-faf6a3/` (live run 2: report, strip, GIF, stall plots,
ledger, events, traces, meta, README). `.gitignore` now ignores `runs/*` except `runs/examples/`.

### Benchmark harness
`baselines.random_start(seed)` (uniform over the free-parameter bounds until geometry/FS2026 pass and
NeuralFoil gives physical downforce; `--start-seed`, recorded in meta.json), `baselines.random_search`
(same gates and promotion rule as the graph), `scripts/benchmark.py` (40 evals, $4 / 1.5 h safety
caps; writes `docs/BENCHMARK.md`). `--max-wall-hours` added. `make lint` covers `scripts/`.

### Benchmark results (`docs/BENCHMARK.md`; runs in `runs/bench/`, not committed)
5 seeded feasible starts (seeds 11, 22, 33, 44, 55), 40 evals, $4 / 1.5 h safety caps.

| method | success | evals to target | est. cost / run | wall clock / run |
|---|---|---|---|---|
| LLM (claude-sonnet-5) | 1/5 | 17 | $1.57 mean ($1.10–2.45) | 18.1 min mean (concurrent) |
| mock | 0/5 | — | $0 | 0.1 min |
| random search | 0/5 | — | $0 | 0.1 min |

- No run hit a safety cap. 4/5 LLM runs and 5/5 mock runs **declared a plateau** before the budget
  (LLM at 16–28 evals): evaluations did not bind. The LLM's failed runs stalled on the camber bound
  with camber position 0.40–0.54; the passing designs are at p 0.30–0.36.
- 1 XFoil evaluation in 25 runs. Counterfactual XFoil gate on every near-target design the screen
  failed: mock 0/51 would pass, LLM 2/26 (both in the successful seed-44 run). The screen cost no
  method a success.

### Known issues / next
- The Chief's plateau rule ("after three non-improving hypotheses") ends LLM runs with a third of the
  budget or more unused; with evaluations meant to be the only binding limit, consider allowing a
  plateau only in the last part of the budget, or widening the trust region instead.
- The screen blocks ~43% of XFoil-feasible designs in the promotion window (by design, for ≤ 5% false
  passes); it blocked live run 2's winner on replay.
- Camber position is the lever that separated success from failure here; the LLM rarely moved it
  far forward from aft starts.

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

### Live run 2: `--llm anthropic --preset hard --max-evals 40 --budget-usd 2` → **target_met**
Run `20261001-201455-faf6a3` (runs/ is gitignored; this is the record). 23 of 40 evals, 69 LLM calls
(0 failed, 0 fallbacks), 264k/94k tokens, **est. $1.47**, 0.28 h. Termination `target_met`.
**Passing design `abb9803ead` (gen 22, XFoil): m 0.09, p 0.36, t 0.13, alpha 8.349 — Cl −1.8526,
Cd 0.02222, stall margin 0.068/deg, no TE separation at alpha+0..+2.** It is on the camber bound.

| gen | fid | status / symptom | m | p | t | α | focus (Chief direction) | CAD change(s): heuristic / Chief |
|---|---|---|---|---|---|---|---|---|
| 0 | NF | MISS / EARLY_STALL | 0.060 | 0.40 | 0.100 | 8.00 | camber +, thick −, alpha + | baseline |
| 1 | NF | MISS / EARLY_STALL | 0.0762 | 0.40 | 0.0953 | 7.00 | camber +, thick −, alpha − | camber + (follows), thick − (follows; against "thicker"), alpha − (follows both) |
| 2 | NF | MISS / INSUFF_LOADING | 0.0897 | 0.38 | 0.0953 | 6.00 | camber +, **pos −**, alpha − | camber +, **pos 0.40→0.38 (fwd)**, alpha − — all follow |
| 3 | NF | MISS / EARLY_STALL | 0.090 | 0.38 | 0.0953 | 7.78 | camber +, alpha +, pos − | camber + (to bound), alpha + — follow |
| 4 | NF | MISS / INSUFF_LOADING | 0.090 | 0.38 | 0.1073 | 7.58 | camber +, thick +, alpha − | alpha −, thick + — follow (EARLY_STALL heuristic) |
| 5 | NF | MISS / EARLY_STALL | 0.090 | 0.38 | 0.1073 | 7.97 | camber +, alpha +, thick free | alpha + — follows |
| 6 | NF | MISS / INSUFF_LOADING | 0.090 | 0.38 | 0.1153 | 6.30 | camber +, thick +, alpha − | thick +, alpha − — follow (alpha against heuristic) |
| 7 | NF | PASS | 0.090 | 0.38 | 0.1153 | 8.00 | camber +, thick +, alpha free | thick +, alpha + — follow |
| 8 | XF | MISS / EARLY_STALL (margin 0.034) | ↑ | | | | promote gen 7 | — |
| 9 | NF | MISS / EARLY_STALL | 0.090 | 0.38 | 0.1073 | 7.971 | thick +, camber +, alpha − | **alpha + overrides Chief −** |
| 10 | NF | MISS / EARLY_STALL | 0.090 | 0.38 | 0.1073 | 7.969 | alpha −, camber +, thick + | **alpha + overrides Chief −** |
| 11 | NF | MISS / EARLY_STALL | 0.090 | 0.38 | 0.1073 | 7.974 | camber +, thick +, alpha − | **alpha + overrides Chief −** |
| 12 | XF | MISS / EARLY_STALL (margin 0.029) | 0.090 | 0.38 | 0.1073 | 7.58 | promote gen 4 | — |
| 13 | NF | MISS / INSUFF_LOADING | 0.090 | 0.38 | 0.1273 | 7.67 | camber +, alpha −, thick + | alpha −, thick + — follow |
| 14 | NF | PASS | 0.090 | 0.38 | 0.1123 | 7.67 | thick +, camber +, alpha − | thick +, alpha − — follow |
| 15 | XF | MISS / EARLY_STALL (margin 0.047) | ↑ | | | | promote gen 14 | — |
| 16 | NF | MISS / EARLY_STALL | 0.090 | **0.44** | 0.1123 | 7.47 | **pos +**, thick +, alpha − | alpha −, thick +, **pos 0.38→0.44 (aft)** — follow |
| 17 | NF | MISS / INSUFF_LOADING | 0.090 | 0.38 | 0.1223 | 7.67 | alpha −, camber +, thick + | alpha −, thick + — follow |
| 18 | NF | MISS / EARLY_STALL | 0.090 | 0.38 | 0.0953 | 7.67 | thick −, camber +, alpha free | thick − (against "thicker"), alpha − — follow Chief |
| 19 | NF | MISS / EARLY_STALL | 0.090 | 0.38 | 0.0973 | 7.67 | camber +, alpha −, thick − | alpha −, thick − — follow Chief |
| 20 | NF | MISS / INSUFF_LOADING | 0.090 | **0.36** | 0.130 | 7.97 | **pos −**, thick −, camber + | **thick + overrides Chief −** (cites EARLY_STALL heuristic), **pos 0.38→0.36 (fwd)** |
| 21 | NF | PASS | 0.090 | 0.36 | 0.130 | 8.35 | camber +, alpha +, thick free | alpha + — follows |
| 22 | XF | **PASS** (margin 0.068) | ↑ | | | | promote gen 21 | — |

- **Sensitivities**: of 34 CAD changes, 1 predicted a sign against the NeuralFoil sensitivity (gen 1,
  thickness); the other 33 match.
- **Chief directions**: 4 logged `chief_cad_disagreement`s (gens 9, 10, 11: alpha; gen 20: thickness).
  Gens 9–11 repeat the same override on the same parent; the Chief kept asking alpha − for three
  generations. Gen 20's override (thicker, per the EARLY_STALL heuristic) produced the parent of the
  passing design.
- **Near-duplicates**: gens 9–11 are gen 5 again with alpha moved by ≤ 0.004°. The CAD hit 3
  exact-duplicate rejections first; the duplicate check is exact-cid only.
- **camber_pos**: moved three times — forward (gen 2, 0.40→0.38), aft (gen 16, 0.38→0.44), forward
  (gen 20, 0.38→0.36); the passing design has p 0.36. The Chief chose camber_pos in gens 2, 3, 16, 20.
- **TE_SEPARATION_MAIN → move camber forward** was never offered: no verdict was TE_SEPARATION_MAIN
  (symptoms: EARLY_STALL 13, INSUFFICIENT_LOADING 6, NONE 4).
- **Parent selection**: no design passed until gen 22, so every parent came from least violation;
  after XFoil rejected gen 4's design (gen 12) the parent moved off it.
- **Screen vs XFoil**: all 4 promotions passed the screen; XFoil rejected 3 on margin (screen 0.052,
  0.055, 0.056 vs XFoil 0.034, 0.029, 0.047) and passed the 4th (0.059 vs 0.068). No screen blocks,
  no direct-to-XFoil steps, no screen overrides in this run.

### Known issues / limits
- The screen passes designs whose NeuralFoil slope is just above 0.05 and whose XFoil slope is
  not (3 of 4 promotions in live run 2). A margin on the screen threshold would block those; not
  changed (calibration said 0.05 blocks 0 of 25 near-target XFoil passes).
- Duplicate detection is exact-cid; alpha nudges of ~0.002° pass as new designs.
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
