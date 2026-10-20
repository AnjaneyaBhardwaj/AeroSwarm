/* Aeroptimize run viewer: replays exported runs (viewer/runs/*.json, written by scripts/export_run.py).
 * Every number on screen comes from the export (the run ledger); agent text is verbatim from the traces.
 * Geometry is never derived here: outlines come precomputed per candidate. Only in-between animation
 * frames are tweened, and numeric readouts snap to recorded values (they are never interpolated). */
"use strict";

const $ = (s) => document.querySelector(s);
// Where the live server is. Empty: the page's own origin (the server also serves this page). Set the
// <meta name="aeroswarm-api"> tag when the page and the server live on different addresses (docs/DEPLOY.md).
const API = (() => {
  const v = (document.querySelector('meta[name="aeroswarm-api"]')?.content || "").trim();
  return v && !v.endsWith("/") ? v + "/" : v;
})();
const SVGNS = "http://www.w3.org/2000/svg";
const BASE_DWELL_MS = 2600; // per generation at 1x
const TWEEN_MS = 750;
const MORPH_MS = 2600;

const PARAM_META = {
  main_camber: { name: "Camber", unit: "% c", scale: 100, dp: 2 },
  main_camber_pos: { name: "Camber position", unit: "% c", scale: 100, dp: 1 },
  main_thickness: { name: "Thickness", unit: "% c", scale: 100, dp: 2 },
  alpha_deg: { name: "Angle of attack", unit: "deg", scale: 1, dp: 2 },
  flap_chord_ratio: { name: "Flap chord", unit: "% c", scale: 100, dp: 1 },
  flap_deflection_deg: { name: "Flap angle", unit: "deg", scale: 1, dp: 1 },
  slot_gap: { name: "Slot gap", unit: "% c", scale: 100, dp: 2 },
  slot_overlap: { name: "Slot overlap", unit: "% c", scale: 100, dp: 2 },
  gurney_h: { name: "Gurney", unit: "% c", scale: 100, dp: 2 },
};
const SHORT = { main_camber: "camber", main_camber_pos: "camber pos", main_thickness: "thickness", alpha_deg: "alpha" };
const SOLVER = { neuralfoil: "NeuralFoil", xfoil: "XFoil", of2d: "OpenFOAM 2D", of3d: "OpenFOAM 3D" };
const RULEBOOK = { "FSAE2027_v1.0": "Formula SAE 2027 v1.0", "FS2026_v1.1": "Formula Student 2026 v1.1", none: "none (checks off)" }; // swarm/cad/regulations.py
const ICON = {
  pass: '<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="currentColor" opacity=".18"/><path d="M4.5 8.2l2.3 2.3 4.7-5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>',
  miss: '<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2" stroke="currentColor" stroke-width="1.8" fill="none"/><circle cx="8" cy="8" r="2.2" fill="currentColor"/></svg>',
  fail: '<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5l7 12.5H1z" fill="currentColor" opacity=".18"/><path d="M8 6v3.6M8 11.6v.4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
};

const S = {
  index: null,
  run: null,
  frames: [],      // generations that have at least one evaluation
  fi: 0,           // current frame index
  playing: false,
  speed: 1,
  nextAt: 0,
  tween: null,     // {from, to, fromP, toP, fromCl, toCl, t0, dur}
  shown: null,     // {outline, params, cl}
  pick: {},        // dial-set start design
  dragging: null,
  morph: null,     // start -> final morph state
  reasoning: false, // agent steps show their verbatim reasoning
  cidParams: {},
  cidOutline: {},
  dataBase: "", // where runs/*.json come from: this page's folder, or the live server's
};

/* ------------------------------------------------------------------ helpers */
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmt = (x, dp) => (x == null || !isFinite(x) ? "—" : Number(x).toFixed(dp));
const signed = (x, dp) => (x == null ? "—" : (x < 0 ? "−" : "+") + Math.abs(x).toFixed(dp));
const clTxt = (x) => (x == null ? "—" : (x < 0 ? "−" : "") + Math.abs(x).toFixed(4));
const cdTxt = (x) => fmt(x, 4); // drag to four places (one drag count) everywhere
const pval = (name, v) => {
  const m = PARAM_META[name] || { scale: 1, dp: 3, unit: "" };
  return (v * m.scale).toFixed(m.dp);
};
const el = (tag, attrs = {}, parent) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
};
const lerp = (a, b, t) => a + (b - a) * t;
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function statusOf(ev) {
  // cls picks the icon; kind picks the colour: only a pass, a screen-only pass and a failed check get one
  if (!ev) return { cls: "", kind: "", text: "—" };
  if (ev.passing) return { cls: "pass", kind: "pass", text: "Pass" };
  const v = ev.verdict || ev.solver_status;
  if (v === "PASS") return { cls: "miss", kind: "screen", text: `Pass at ${SOLVER[ev.solver] || ev.solver} only` };
  if (v === "TARGET_MISS") return { cls: "miss", kind: "miss", text: "Target miss" };
  return { cls: "fail", kind: "fail", text: cap1(String(v || "FAILED").replaceAll("_", " ").toLowerCase()) };
}
const headOf = (g) => (g && g.head >= 0 ? g.evals[g.head] : null);
const dur = (ms) => ms / S.speed;
const listJoin = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
const cap1 = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const smooth = () => (matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

/* ------------------------------------------------------------------ loading */
async function fetchJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function boot() {
  initTheme();
  wireControls();
  wireTips();
  wireIntro();
  try {
    S.index = await fetchJSON(`${S.dataBase}runs/index.json`);
  } catch (e) {
    fatal(`Could not load runs/index.json (${e.message}). Serve the viewer over HTTP: <code>python -m http.server -d viewer</code>, and export a run with <code>scripts/export_run.py</code>.`);
    return;
  }
  fillSelect();
  const sel = $("#run-select");
  sel.addEventListener("change", () => { detachLive(); loadRun(sel.value, { autoplay: true }); });
  const q = new URLSearchParams(location.search);
  const want = q.get("run");
  const first = S.index.runs.find((r) => r.name === want || r.file === want) || S.index.runs[0];
  if (!first) return fatal("No exported runs in runs/index.json.");
  // The page opens on the result (last generation, paused); "Watch the replay" plays it from the start.
  const autoplay = q.get("autoplay") === "1";
  await loadRun(first.file, { autoplay, gen: q.get("gen") ?? (autoplay ? null : "last") });
  if (q.get("intro") === "1") openIntro();
  if (q.get("speed")) setSpeed(Number(q.get("speed")));
  requestAnimationFrame(loop);
  probeLive();
}

function fillSelect() {
  const sel = $("#run-select");
  const cur = sel.value;
  sel.innerHTML = "";
  for (const r of S.index.runs) {
    const o = document.createElement("option");
    o.value = r.file;
    const res = r.outcome.result === "no_pass" ? "no pass" : "target met";
    o.textContent = `${r.name} · ${r.is_mock ? "MOCK" : "LLM"} · ${res}`;
    sel.appendChild(o);
  }
  if (cur) sel.value = cur;
  sel.hidden = S.index.runs.length < 2; // one run: nothing to choose
}

function fatal(html) {
  $("#steps").innerHTML = `<li class="waiting">${html}</li>`;
}

async function loadRun(file, { autoplay = true, gen = null, keepPick = false } = {}) {
  const data = await fetchJSON(`${S.dataBase}runs/${file}`);
  $("#run-select").value = file;
  setRun(data, { keepPick });
  const startFi = gen === "last" ? S.frames.length - 1
    : gen != null ? S.frames.findIndex((g) => g.gen >= Number(gen)) : 0;
  goTo(Math.max(0, startFi), { instant: true });
  setPlaying(autoplay && S.frames.length > 1);
}

function setRun(data, { keepPick = false } = {}) {
  S.run = data;
  S.frames = data.generations.filter((g) => g.head >= 0);
  S.cidParams = {};
  for (const g of data.generations) for (const e of g.evals) S.cidParams[e.cid] ??= e.params;
  S.cidParams[data.start_cid] ??= data.start;
  S.cidOutline = data.outlines;
  S.morph = null;
  $("#btn-morph").classList.remove("on");
  if (!keepPick) S.pick = { ...data.start };
  S.shown = null;
  renderHero();
  renderFacts();
  renderDials();
  renderNearest();
  layoutStage();
  $("#scrubber").max = Math.max(0, S.frames.length - 1);
  $("#gen-of").textContent = `of ${S.frames.length ? S.frames[S.frames.length - 1].gen : 0}`;
  if (!S.frames.length) renderWaiting();
  checkLiveStart();
}

/* Live run before its first generation: the start outline and no steps yet. */
function renderWaiting() {
  const r = S.run;
  S.shown = { outline: r.outlines[r.start_cid], params: r.start, cl: null, clLabel: "", ghostCid: null };
  $("#gen-num").textContent = "–";
  $("#gen-of").hidden = true;
  const st = $("#stage-status");
  st.className = "status";
  st.textContent = "Starting";
  for (const id of ["#ro-cl", "#ro-cd", "#ro-solver", "#ro-stall"]) $(id).textContent = "—";
  for (const id of ["#ro-cl", "#ro-cd"]) $(id).classList.remove("ok");
  $("#story").textContent = "The run is starting: the Chief is planning and the start design is being solved.";
  updateDials(r.start);
  stageFoot();
  drawStage();
  drawPolar();
  $("#steps").innerHTML = `<li class="waiting">Waiting for generation 0.</li>`;
}

/* ------------------------------------------------------------------ headline + facts */
/* The headline's result: the run's outcome from the ledger against the spec (or a live run's progress). */
function renderHero() {
  const r = S.run, s = r.spec, o = r.outcome;
  const verdict = $("#hero-verdict"), note = $("#hero-note");
  const tile = (k, v, t, ok) => `<div class="tile ${ok == null ? "" : ok ? "ok" : "bad"}"><span class="k">${k}</span><span class="v">${v}</span><span class="t">${t}</span></div>`;
  const num = (x) => (x < 0 ? "−" : "") + Math.abs(x); // spec values as written (−1.83, not −1.8300)
  const clT = `target ${num(s.target_cl)} ± ${s.cl_tol}`, cdT = `at most ${s.cd_max}`;
  const inCl = (cl) => cl != null && Math.abs(cl - s.target_cl) <= s.cl_tol;
  const inCd = (cd) => cd != null && cd <= s.cd_max;
  const flags = [];
  if (r.is_mock) flags.push(`<b>Mock run:</b> ${esc((r.mock_notice || "a rule-based stand-in, not an LLM").replace(/\.\s*$/, ""))}.`);
  if (r.llm_valid === false) flags.push("<b>Invalid LLM run</b> (see meta.json llm_health).");
  $("#watch").textContent = liveRunning() ? "Follow the run" : "Watch the replay";
  $("#hero-live").hidden = !S.live.available || liveRunning();

  if (r._liveError || liveRunning()) {
    const last = headOf(S.frames[S.frames.length - 1]);
    verdict.className = `verdict ${r._liveError ? "fail" : ""}`;
    verdict.innerHTML = r._liveError ? `${ICON.fail}The live run stopped with an error` : `<span class="spin" aria-hidden="true"></span>Live run in progress`;
    $("#hero-tiles").innerHTML = tile("Downforce (Cl), latest", last ? clTxt(last.cl) : "—", clT, last ? inCl(last.cl) : null)
      + tile("Drag (Cd), latest", last ? cdTxt(last.cd) : "—", cdT, last ? inCd(last.cd) : null);
    note.innerHTML = [esc(r._liveError || S.live.progress || "Starting…"), ...flags].join(" ");
    return;
  }
  let line;
  if (o.result !== "no_pass") {
    const sm = finalRecord()?.e.stall?.dcl_dalpha;
    verdict.className = "verdict pass";
    verdict.innerHTML = `${ICON.pass}Target met in ${o.evals_to_target} evaluations`;
    $("#hero-tiles").innerHTML = tile("Downforce (Cl)", clTxt(o.cl), clT, inCl(o.cl)) + tile("Drag (Cd)", cdTxt(o.cd), cdT, inCd(o.cd));
    line = `Confirmed by ${esc(SOLVER[o.solver] || o.solver)} at generation ${o.generation}, with a healthy stall margin${sm != null ? ` (${sm.toFixed(3)}/°)` : ""}.`
      + (r.cost_usd != null ? ` Estimated LLM cost $${r.cost_usd.toFixed(2)}.` : "");
  } else {
    verdict.className = "verdict nopass";
    verdict.innerHTML = `${ICON.miss}No passing design in ${r.evals} evaluations`;
    $("#hero-tiles").innerHTML = tile("Closest Cl", clTxt(o.cl), clT, o.cl != null ? inCl(o.cl) : null)
      + tile("Closest Cd", cdTxt(o.cd), cdT, o.cd != null ? inCd(o.cd) : null);
    const f = o.failing || [];
    line = o.cid
      ? `The closest design (generation ${o.generation}, ${esc(SOLVER[o.solver] || o.solver)}) fails: ${esc(f[0] || "—")}${f.length > 1 ? ` (+${f.length - 1} more)` : ""}.`
      : "No design was evaluated.";
  }
  note.innerHTML = [line, ...flags].join(" ");
}

function renderFacts() {
  const r = S.run, s = r.spec;
  $("#spec").innerHTML = [
    ["Target Cl", `${clTxt(s.target_cl)} ± ${s.cl_tol}`],
    ["Cd max", s.cd_max],
    ["Reynolds", s.reynolds.toExponential(1).replace("e+", "e")],
    ["Section", s.component === "wing_1el" ? "single element" : s.component],
    ["Rulebook", RULEBOOK[s.rulebook] || s.rulebook],
    ["Budget", `${s.max_evals} evaluations`],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
  const rows = [
    ["Termination", r.termination || "—"],
    ["Evaluations", r.evals],
    ["LLM calls", r.llm_calls ?? "—"],
    ["Est. LLM cost", r.cost_usd != null ? `$${r.cost_usd.toFixed(2)}` : "—"],
    ["Wall clock", r.wall_hours != null ? `${(r.wall_hours * 60).toFixed(0)} min` : "—"],
    ["Run", r.run_id],
  ];
  if (r.start_seed != null) rows.splice(5, 0, ["Start seed", r.start_seed]);
  $("#run-facts").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
  $("#cad-box").innerHTML = `<div class="dhead"><h3>CAD files</h3></div>${cadLinks(r)}`;
  $("#cad-box").hidden = !r.cad;

  const b = r.baseline, box = $("#baseline");
  if (!b) { box.hidden = true; return; }
  box.hidden = false;
  const swarm = r.outcome.result === "no_pass" ? "no pass" : `target met in ${r.outcome.evals_to_target} evals`;
  const opt = b.result === "no_pass"
    ? `no pass in ${b.evals} evals; closest Cl ${clTxt(b.cl)}, Cd ${cdTxt(b.cd)} (${SOLVER[b.solver] || b.solver})`
    : `target met in ${b.evals_to_target} evals (Cl ${clTxt(b.cl)}, Cd ${cdTxt(b.cd)})`;
  box.innerHTML = `<div class="dhead"><h3>Compared with Optuna</h3><span class="hint">same start</span></div>
    <p><b>Swarm:</b> ${esc(swarm)}</p>
    <p><b>Optuna TPE:</b> ${esc(opt)}</p>
    ${b.failing && b.failing.length ? `<div class="why">Its closest design fails: ${esc(b.failing[0])}</div>` : ""}
    <div class="why">Same spec, checks and budget, no LLM; sampler seed ${esc(b.seed)}. Run with the current pipeline code.</div>`;
}

/* ------------------------------------------------------------------ dials */
const DIAL = { cx: 56, cy: 48, r: 36, a0: 135, sweep: 270 };
function polar(cx, cy, r, deg) {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function arc(cx, cy, r, a0, a1) {
  const [x0, y0] = polar(cx, cy, r, a0), [x1, y1] = polar(cx, cy, r, a1);
  const large = a1 - a0 > 180 ? 1 : 0;
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function renderDials() {
  const box = $("#dials");
  box.innerHTML = "";
  for (const name of S.run.free_params) {
    const m = PARAM_META[name] || { name, unit: "", scale: 1, dp: 3 };
    const [lo, hi] = S.run.bounds[name];
    const wrap = document.createElement("div");
    wrap.className = "dial";
    const svg = el("svg", { viewBox: "0 0 112 92", tabindex: 0, role: "slider", "aria-label": `${m.name} of the start design`, "aria-valuemin": lo, "aria-valuemax": hi });
    el("path", { class: "track", d: arc(DIAL.cx, DIAL.cy, DIAL.r, DIAL.a0, DIAL.a0 + DIAL.sweep) }, svg);
    const fill = el("path", { class: "fill" }, svg);
    const pick = el("circle", { class: "pick", r: 2.6 }, svg);
    const knob = el("circle", { class: "knob", r: 6 }, svg);
    const val = el("text", { class: "val", x: DIAL.cx, y: DIAL.cy + 4 }, svg);
    const unit = el("text", { class: "unit", x: DIAL.cx, y: DIAL.cy + 18 }, svg);
    unit.textContent = m.unit;
    el("title", {}, svg).textContent = `${m.name}: ${(lo * m.scale).toFixed(0)}–${(hi * m.scale).toFixed(0)} ${m.unit}. Drag up/down, scroll, or use the arrow keys.`;
    wrap.appendChild(svg);
    const nm = document.createElement("div");
    nm.className = "name";
    nm.textContent = m.name;
    wrap.appendChild(nm);
    box.appendChild(wrap);
    svg._parts = { fill, knob, val, pick, lo, hi, name, svg };
    wireDial(svg, name, lo, hi);
  }
}

function setDial(svg, value, { text = true } = {}) {
  const { fill, knob, val, pick, lo, hi, name } = svg._parts;
  const f = Math.min(1, Math.max(0, (value - lo) / (hi - lo)));
  const a = DIAL.a0 + DIAL.sweep * f;
  fill.setAttribute("d", f > 0.002 ? arc(DIAL.cx, DIAL.cy, DIAL.r, DIAL.a0, a) : "");
  const [x, y] = polar(DIAL.cx, DIAL.cy, DIAL.r, a);
  knob.setAttribute("cx", x);
  knob.setAttribute("cy", y);
  if (text) val.textContent = pval(name, value);
  const pv = S.pick[name];
  if (pv != null) {
    const fp = Math.min(1, Math.max(0, (pv - lo) / (hi - lo)));
    const [px, py] = polar(DIAL.cx, DIAL.cy, DIAL.r + 9, DIAL.a0 + DIAL.sweep * fp);
    pick.setAttribute("cx", px);
    pick.setAttribute("cy", py);
  }
  svg.setAttribute("aria-valuenow", value);
  svg.setAttribute("aria-valuetext", `${pval(name, value)} ${PARAM_META[name]?.unit || ""}`);
}

function updateDials(params, { text = true } = {}) {
  for (const svg of document.querySelectorAll(".dial svg")) {
    const n = svg._parts.name;
    const v = S.dragging ? S.pick[n] : params[n];
    setDial(svg, v, { text: S.dragging ? true : text });
  }
}

function wireDial(svg, name, lo, hi) {
  let y0 = 0, v0 = 0;
  const range = hi - lo;
  const change = (v) => {
    S.pick[name] = Math.min(hi, Math.max(lo, v));
    setDial(svg, S.pick[name]);
    renderNearest();
    checkLiveStart();
  };
  svg.addEventListener("pointerdown", (e) => {
    svg.setPointerCapture(e.pointerId);
    S.dragging = name;
    setPlaying(false);
    y0 = e.clientY;
    v0 = S.pick[name] ?? S.run.start[name];
    for (const s of document.querySelectorAll(".dial svg")) setDial(s, S.pick[s._parts.name]);
  });
  svg.addEventListener("pointermove", (e) => {
    if (S.dragging !== name) return;
    change(v0 + ((y0 - e.clientY) / 160) * range);
  });
  const end = () => {
    if (S.dragging !== name) return;
    S.dragging = null;
    commitPick();
  };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);
  svg.addEventListener("keydown", (e) => {
    const step = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1, PageUp: 5, PageDown: -5 }[e.key];
    if (!step) return;
    e.preventDefault();
    setPlaying(false);
    change((S.pick[name] ?? S.run.start[name]) + step * range * 0.01);
    clearTimeout(svg._t);
    svg._t = setTimeout(commitPick, 700);
  });
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    setPlaying(false);
    change((S.pick[name] ?? S.run.start[name]) - Math.sign(e.deltaY) * range * 0.01);
    clearTimeout(svg._t);
    svg._t = setTimeout(commitPick, 700);
  }, { passive: false });
}

function nearestRuns() {
  const names = S.run.free_params;
  const b = S.index.bounds;
  return S.index.runs
    .map((r) => {
      const terms = names.map((n) => {
        const [lo, hi] = b[n];
        return ((r.start[n] ?? 0) - (S.pick[n] ?? 0)) / (hi - lo);
      });
      const d = Math.sqrt(terms.reduce((a, t) => a + t * t, 0) / terms.length);
      return { r, d, terms };
    })
    .sort((a, b2) => a.d - b2.d);
}

function renderNearest() {
  if (!S.index) return;
  const best = nearestRuns()[0];
  if (!best) return;
  const names = S.run.free_params;
  const diffs = names
    .map((n) => {
      const dv = S.pick[n] - best.r.start[n];
      const m = PARAM_META[n];
      return Math.abs(dv * m.scale) < Math.pow(10, -m.dp) / 2 ? null : `${SHORT[n] || n} ${dv * m.scale >= 0 ? "+" : "−"}${Math.abs(dv * m.scale).toFixed(m.dp)}`;
    })
    .filter(Boolean);
  const res = best.r.outcome.result === "no_pass" ? "no pass" : "target met";
  const exact = best.d < 1e-6;
  $("#nearest").innerHTML = `${exact ? "Recorded start:" : "Nearest recorded start:"} <b>${esc(best.r.name)}</b>
    (${best.r.is_mock ? "mock" : "LLM"}, ${res})<br>distance <span class="dist">${best.d.toFixed(3)}</span>
    <span title="RMS of the per-parameter differences, each scaled by its allowed range (0 = identical start)">(normalized)</span>
    ${S.index.runs.length < 2 ? `<div class="diffs">only ${S.index.runs.length} run exported</div>` : ""}
    ${diffs.length ? `<div class="diffs">your pick vs its start: ${esc(diffs.join(", "))}</div>` : ""}`;
}

async function commitPick() {
  if (liveRunning()) { renderNearest(); return; } // the dials set the next live run's start; keep watching this one
  const best = nearestRuns()[0];
  if (!best) return;
  if (best.r.file !== $("#run-select").value) await loadRun(best.r.file, { autoplay: true, keepPick: true });
  else { renderNearest(); goTo(0, { instant: true }); setPlaying(true); }
  renderNearest();
}

/* ------------------------------------------------------------------ stage (wing) */
const ST = { w: 800, h: 300, k: 1, ox: 0, oy: 0 };
function layoutStage() {
  const svg = $("#stage");
  const rect = svg.getBoundingClientRect();
  ST.w = Math.max(320, rect.width);
  ST.h = Math.max(200, rect.height);
  svg.setAttribute("viewBox", `0 0 ${ST.w} ${ST.h}`);
  if (!S.run) return;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const ol of Object.values(S.run.outlines)) for (const [x, y] of ol) {
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  // room for the freestream arrow (left), the downforce arrow (below) and labels
  const maxCl = Math.max(Math.abs(S.run.spec.target_cl), ...S.run.generations.flatMap((g) => g.evals.map((e) => Math.abs(e.cl || 0))));
  ST.arrowK = 0.13;
  const X0 = x0 - 0.2, X1 = x1 + 0.06, Y0 = y0 - maxCl * ST.arrowK - 0.07, Y1 = y1 + 0.06;
  ST.k = Math.min((ST.w - 30) / (X1 - X0), (ST.h - 16) / (Y1 - Y0));
  ST.ox = (ST.w - (X1 - X0) * ST.k) / 2 - X0 * ST.k;
  ST.oy = (ST.h - (Y1 - Y0) * ST.k) / 2 + Y1 * ST.k;
  drawStage();
}
const sx = (x) => ST.ox + x * ST.k;
const sy = (y) => ST.oy - y * ST.k;
const path = (ol) => (ol ? "M" + ol.map(([x, y]) => `${sx(x).toFixed(1)} ${sy(y).toFixed(1)}`).join("L") + "Z" : "");
function tweenOutline(a, b, t) {
  if (!a || a.length !== b.length) return b;
  return a.map(([x, y], i) => [lerp(x, b[i][0], t), lerp(y, b[i][1], t)]);
}

function arrowHead(g, x, y, ang, cls, size = 9) {
  const a = (ang * Math.PI) / 180, s = size;
  const p = [[x, y], [x - s * Math.cos(a - 0.45), y - s * Math.sin(a - 0.45)], [x - s * Math.cos(a + 0.45), y - s * Math.sin(a + 0.45)]];
  el("path", { class: cls, d: `M${p.map((q) => q.join(" ")).join("L")}Z` }, g);
}

function drawStage() {
  const svg = $("#stage");
  svg.innerHTML = "";
  if (!S.run || !S.shown) return;
  const g = el("g", {}, svg);
  // freestream
  const fy = sy(0);
  el("line", { class: "grid-line", x1: sx(-0.18), x2: sx(1.06), y1: fy, y2: fy, "stroke-dasharray": "2 5" }, g);
  el("line", { class: "arrow", x1: sx(-0.18), x2: sx(-0.06), y1: fy, y2: fy }, g);
  arrowHead(g, sx(-0.06), fy, 0, "arrow-head", 8);
  const ft = el("text", { x: sx(-0.18), y: fy - 8 }, g);
  ft.textContent = "flow";
  // chord scale
  for (const xc of [0, 0.25, 0.5, 0.75, 1]) {
    const t = el("text", { x: sx(xc), y: ST.h - 6, "text-anchor": "middle", class: "mono" }, g);
    t.textContent = xc === 0 ? "x/c 0" : String(xc);
  }

  const m = S.morph;
  if (m) {
    el("path", { class: "start-ol", d: path(S.cidOutline[m.startCid]) }, g);
    el("path", { class: "final-ol", d: path(S.cidOutline[m.finalCid]) }, g);
  } else {
    const ghost = S.shown.ghostCid && S.cidOutline[S.shown.ghostCid];
    if (ghost) el("path", { class: "ghost", d: path(ghost) }, g);
  }
  el("path", { class: "wing", d: path(S.shown.outline) }, g);

  // downforce arrow from below the quarter chord, length ∝ |Cl|; dashed tick = target
  const ol = S.shown.outline;
  let lowY = Infinity;
  for (const [x, y] of ol) if (x > 0.15 && x < 0.4) lowY = Math.min(lowY, y);
  const ax = sx(0.27), ay = sy(lowY) + 6;
  const L = Math.abs(S.shown.cl || 0) * ST.arrowK * ST.k;
  const T = Math.abs(S.run.spec.target_cl) * ST.arrowK * ST.k;
  el("line", { class: "df-target", x1: ax - 16, x2: ax + 16, y1: ay + T, y2: ay + T }, g);
  const tl = el("text", { x: ax + 20, y: ay + T + 4, class: "mono" }, g);
  tl.textContent = `target ${clTxt(S.run.spec.target_cl)}`;
  if (L > 4) {
    el("line", { class: "df", x1: ax, x2: ax, y1: ay, y2: ay + L - 6 }, g);
    arrowHead(g, ax, ay + L, 90, "df-head", 11);
  }
  const dl = el("text", { x: ax - 12, y: ay + Math.max(L * 0.55, 14), "text-anchor": "end", class: "mono" }, g);
  dl.textContent = S.shown.clLabel ?? "";
}

function stageFoot() {
  const items = S.morph
    ? [["var(--chief)", "start design (gen 0)", "2 3"], ["var(--good)", S.run.outcome.result === "no_pass" ? "closest candidate" : "final passing design", ""]]
    : [["var(--accent)", "this generation", ""], ["var(--ghost)", "the design it started from", "5 4"]];
  $("#stage-foot").innerHTML =
    items.map(([c, t, d]) => `<span><i class="sw" style="border-color:${c};${d ? "border-top-style:dashed" : ""}"></i>${t}</span>`).join("") +
    `<span>arrow: downforce ∝ |Cl|</span><span>upside down, as on a race car</span>`;
}

/* ------------------------------------------------------------------ frames */
function goTo(fi, { instant = false } = {}) {
  if (!S.frames.length) return;
  fi = Math.max(0, Math.min(S.frames.length - 1, fi));
  const g = S.frames[fi];
  const ev = headOf(g);
  const to = S.cidOutline[ev.cid];
  const ghostCid = ev.parent_cid || g.parent?.cid || null;
  if (S.morph) stopMorph();
  if (instant || !S.shown) {
    S.shown = { outline: to, params: ev.params, cl: ev.cl, clLabel: `Cl ${clTxt(ev.cl)}`, ghostCid };
    S.tween = null;
  } else {
    S.tween = { from: S.shown.outline, to, fromP: S.shown.params, toP: ev.params, fromCl: S.shown.cl ?? ev.cl, toCl: ev.cl, t0: performance.now(), dur: dur(TWEEN_MS), ghostCid, label: `Cl ${clTxt(ev.cl)}` };
  }
  S.fi = fi;
  S.nextAt = performance.now() + dur(BASE_DWELL_MS);
  renderFrame();
}

function renderFrame() {
  const g = S.frames[S.fi], ev = headOf(g), spec = S.run.spec;
  $("#gen-num").textContent = g.gen;
  $("#gen-of").hidden = false;
  $("#scrubber").value = S.fi;
  const st = statusOf(ev);
  const status = $("#stage-status");
  status.className = `status ${st.kind}`;
  status.innerHTML = `${ICON[st.cls] || ""}${esc(st.text)}`;
  status.title = (ev.failing || []).join("\n");
  $("#ro-cl").textContent = clTxt(ev.cl);
  $("#ro-cd").textContent = cdTxt(ev.cd);
  // green when inside the target band / under the drag cap
  $("#ro-cl").classList.toggle("ok", ev.cl != null && Math.abs(ev.cl - spec.target_cl) <= spec.cl_tol);
  $("#ro-cd").classList.toggle("ok", ev.cd != null && ev.cd <= spec.cd_max);
  $("#ro-solver").textContent = (SOLVER[ev.solver] || ev.solver) + (ev.solver_level != null ? ` L${ev.solver_level}` : "");
  const sm = ev.stall;
  $("#ro-stall").textContent = sm && sm.dcl_dalpha != null ? `${sm.dcl_dalpha.toFixed(3)}/° ${sm.source === "xfoil_probe" ? "XF" : "NF"}` : "—";
  $("#ro-stall").title = sm ? `d|Cl|/dα ${sm.dcl_dalpha} vs threshold ${sm.threshold} (${sm.source === "xfoil_probe" ? "XFoil α+1/α+2 probe" : "NeuralFoil screen"}); ${sm.ok ? "ok" : "fails"}` : "no stall-margin evidence for this record";
  $("#story").innerHTML = narrate(g);
  if (!S.tween) updateDials(ev.params);
  stageFoot();
  drawStage();
  renderSteps();
  drawPolar();
}

function loop(now) {
  if (S.tween) {
    const t = Math.min(1, (now - S.tween.t0) / S.tween.dur), e = ease(t);
    const tw = S.tween;
    const params = {};
    for (const k of Object.keys(tw.toP)) params[k] = lerp(tw.fromP?.[k] ?? tw.toP[k], tw.toP[k], e);
    S.shown = { outline: tweenOutline(tw.from, tw.to, e), params, cl: lerp(tw.fromCl ?? 0, tw.toCl ?? 0, e), clLabel: t >= 1 ? tw.label : "", ghostCid: tw.ghostCid };
    updateDials(params, { text: t >= 1 });
    drawStage();
    if (t >= 1) { S.shown.params = tw.toP; S.tween = null; }
  }
  if (S.morph) stepMorph(now);
  if (S.playing && !S.tween && now >= S.nextAt) {
    if (S.fi < S.frames.length - 1) goTo(S.fi + 1);
    else if (!liveRunning()) setPlaying(false);
  }
  requestAnimationFrame(loop);
}

function setPlaying(on) {
  S.playing = on;
  $("#play-icon").setAttribute("d", on ? "M7 5h4v14H7zM13 5h4v14h-4z" : "M7 5v14l12-7z");
  if (on) {
    if (S.morph) stopMorph(true);
    if (S.fi >= S.frames.length - 1) goTo(0, { instant: true });
    S.nextAt = performance.now() + dur(BASE_DWELL_MS) * 0.6;
  }
}

/* The headline's button: play the recorded run from generation 0 (or follow a live one), bringing the replay into view. */
function watchReplay() {
  if (!liveRunning() && S.frames.length) {
    if (S.morph) stopMorph(true);
    goTo(0, { instant: true });
    setPlaying(S.frames.length > 1);
  }
  const mv = $("#main-view"), b = mv.getBoundingClientRect();
  if (b.top < 0 || b.bottom > window.innerHeight) mv.scrollIntoView({ behavior: smooth(), block: "start" });
}
function setSpeed(v) {
  S.speed = v;
  for (const b of document.querySelectorAll(".speed button")) b.classList.toggle("on", Number(b.dataset.speed) === v);
}

/* ------------------------------------------------------------------ result record + morph */
function finalRecord() {
  const o = S.run.outcome;
  for (const g of S.run.generations) for (const e of g.evals) if (e.cid === o.cid && e.solver === o.solver && e.cl === o.cl) return { g, e };
  return null;
}
/* Download links for the run's CAD files (FreeCAD document, STEP, coordinates), built by the exporter. */
function cadLinks(r) {
  const c = r.cad;
  if (!c) return "";
  if (c.error) return `<div class="cad-files">Not built (${esc(c.error)}).</div>`;
  const href = (f) => `${S.dataBase}runs/${c.dir}/${encodeURIComponent(f)}`;
  const kinds = [["fcstd", "FreeCAD model"], ["step", "STEP"], ["dat", "Coordinates (.dat)"]];
  const links = kinds.filter(([k]) => c.files[k]).map(([k, t]) => `<a href="${href(c.files[k])}" download>${t}</a>`).join("");
  const what = c.final_label && c.final_label.startsWith("closest") ? "closest candidate" : "optimized design";
  return `<div class="cad-files">The start and the ${what}, ${c.chord_mm} mm chord, built in FreeCAD ${esc(c.check?.freecad_version || "")}.<span class="dl">${links}</span></div>`;
}

function toggleMorph() {
  if (S.morph) { stopMorph(); return; }
  const o = S.run.outcome;
  if (!o.cid || !S.frames.length) return;
  setPlaying(false);
  const startEv = headOf(S.frames[0]);
  const fr = finalRecord();
  S.morph = { startCid: startEv.cid, finalCid: o.cid, startEv, finalEv: fr?.e, t0: performance.now(), done: false };
  $("#btn-morph").classList.add("on");
  stageFoot();
  $("#gen-num").textContent = `0→${o.generation}`;
  $("#gen-of").hidden = true;
  for (const id of ["#ro-cl", "#ro-cd"]) $(id).classList.remove("ok");
  const st = statusOf(fr?.e);
  $("#stage-status").className = `status ${st.kind}`;
  $("#stage-status").innerHTML = `${ICON[st.cls] || ""}Start → ${o.result === "no_pass" ? "closest" : "final"}`;
  $("#ro-cl").textContent = `${clTxt(startEv.cl)} → ${clTxt(o.cl)}`;
  $("#ro-cd").textContent = `${cdTxt(startEv.cd)} → ${cdTxt(o.cd)}`;
  $("#ro-solver").textContent = `${SOLVER[startEv.solver]} → ${SOLVER[o.solver] || o.solver}`;
  const sm = (e) => (e?.stall?.dcl_dalpha != null ? `${e.stall.dcl_dalpha.toFixed(3)}` : "—");
  $("#ro-stall").textContent = `${sm(startEv)} → ${sm(fr?.e)}/°`;
}
function stepMorph(now) {
  const m = S.morph;
  // forward, hold, back, hold — loops until the viewer leaves morph mode
  const cyc = MORPH_MS * 2 + 1800;
  const t = (now - m.t0) % cyc;
  let f;
  if (t < MORPH_MS) f = ease(t / MORPH_MS);
  else if (t < MORPH_MS + 900) f = 1;
  else if (t < MORPH_MS * 2 + 900) f = 1 - ease((t - MORPH_MS - 900) / MORPH_MS);
  else f = 0;
  const a = S.cidOutline[m.startCid], b = S.cidOutline[m.finalCid];
  const pa = m.startEv.params, pb = m.finalEv?.params || pa;
  const params = {};
  for (const k of Object.keys(pa)) params[k] = lerp(pa[k], pb[k], f);
  S.shown = { outline: tweenOutline(a, b, f), params, cl: lerp(m.startEv.cl, S.run.outcome.cl, f), clLabel: f === 1 ? `Cl ${clTxt(S.run.outcome.cl)}` : f === 0 ? `Cl ${clTxt(m.startEv.cl)}` : "" };
  updateDials(params, { text: f === 0 || f === 1 });
  drawStage();
}
function stopMorph(silent) {
  S.morph = null;
  $("#btn-morph").classList.remove("on");
  if (!silent) goTo(S.fi, { instant: true });
}

/* ------------------------------------------------------------------ agent steps */
// One line per step, written by code from the export's structured fields (never paraphrasing agent text).
// "Show reasoning" adds each agent's own words under its line, verbatim from the traces.
function dirArrow(d) { return d === "+" ? "↑" : d === "-" ? "↓" : "↕"; }
const EVENT = {
  screen_override: "the Chief overrode the stall screen",
  screen_override_refused: "code refused a stall-screen override",
  direct_xfoil_screened_out: "a direct XFoil request was screened out",
  screen_xfoil_disagreement: "NeuralFoil and XFoil disagree",
  xfoil_recovery: "XFoil needed a recovery step",
  xfoil_ladder_exhausted: "XFoil failed at every recovery level",
  escalate_to_xfoil: "escalated to XFoil",
  cad_fallback: "the CAD step fell back to code",
  cad_attempts_exhausted: "the CAD agent ran out of attempts",
  llm_error: "an LLM call failed",
  llm_error_reused_strategy: "an LLM call failed and the last plan was reused",
  llm_error_numeric_verdict: "the Critic call failed and the numeric verdict was used",
  cost_cap_reached: "the cost cap was reached",
  llm_run_aborted: "the run was aborted after LLM failures",
};
const QUIET_EVENTS = ["inner_optimizer_finished", "geometry_rejected", "proposal_rejected"]; // shown in their own steps

function setReasoning(on) {
  S.reasoning = on;
  $("#steps").classList.toggle("show", on);
  $("#steps-note").hidden = !on;
  const b = $("#reasoning-toggle");
  b.textContent = on ? "Hide reasoning" : "Show reasoning";
  b.setAttribute("aria-expanded", String(on));
  if (on) setPlaying(false); // reading needs a still frame
}

function renderSteps() {
  const g = S.frames[S.fi];
  $("#steps").innerHTML = stepRows(g, S.fi).map((s) => `<li class="step ${s.cls}">
    <span class="who" data-tip="${esc(s.tip)}">${s.who}</span>
    <div><p class="line">${s.line}</p>${s.why ? `<div class="why">${s.why}</div>` : ""}</div></li>`).join("");
}

function stepRows(g, i) {
  const ev = headOf(g), rows = [];
  const parentP = S.cidParams[g.parent?.cid || ev?.parent_cid] || null;
  const c = g.chief;
  if (c) {
    const tags = [c.mode === "inner_optimizer" ? "inner optimizer" : "reasoned step", SOLVER[c.fidelity] || c.fidelity, `trust radius ${c.trust_radius}`];
    rows.push({
      cls: "chief", who: "Chief", tip: TIP.chief, line: chiefLine(c),
      why: `<p class="quote">${esc(c.hypothesis)}</p>
        ${c.focus.length ? `<div class="focus">${c.focus.map((f) => `<span>${esc(SHORT[f.name] || f.name)} ${dirArrow(f.direction)}${f.locked ? " (locked)" : ""}</span>`).join("")}</div>` : ""}
        <div class="note">${esc(tags.join(" · "))}</div>
        ${c.screen_override ? `<div class="override"><b>Screen override:</b> ${esc(c.screen_override)}</div>` : ""}
        ${g.parent && i > 0 ? `<div class="note"><span data-tip="${esc(TIP.parent)}">Starts from</span> <code>${esc(g.parent.cid)}</code>: ${esc(g.parent.why)}</div>` : ""}`,
    });
  }
  if (g.cad.length) rows.push({ cls: "cad", who: "CAD", tip: TIP.cad, line: cadLine(g, parentP), why: cadWhy(g, parentP) });
  const inner = g.notes.find((n) => n.event === "inner_optimizer_finished");
  if (inner) {
    rows.push({
      cls: "sys", who: "Optuna", tip: TIP.optuna,
      line: `Ran ${esc(inner.evals)} quick evaluations without an LLM; stopped: ${esc(String(inner.stopped).replaceAll("_", " "))}.`,
      why: inner.promotable?.length ? `<div class="note">Promotable: ${esc(inner.promotable.join(", "))}</div>` : "",
    });
  }
  if (ev) rows.push({ cls: "sys", who: "Solver", tip: TIP.solver, line: solverLine(g), why: solverWhy(g) });
  const cr = g.critic;
  if (cr) {
    rows.push({
      cls: "critic", who: "Critic", tip: TIP.critic, line: criticLine(g),
      why: `<div class="note">${esc([cr.status, cr.symptom, cr.confidence != null ? `confidence ${cr.confidence}` : null].filter(Boolean).join(" · "))}</div>
        ${cr.evidence.length ? `<ul class="ev">${cr.evidence.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`,
    });
  }
  const other = g.notes.filter((n) => !QUIET_EVENTS.includes(n.event));
  if (other.length || g.llm_failures.length) {
    const names = [...new Set(other.map((n) => EVENT[n.event] || n.event.replaceAll("_", " ")))];
    if (g.llm_failures.length) names.push(`${g.llm_failures.length === 1 ? "an LLM call" : `${g.llm_failures.length} LLM calls`} failed`);
    rows.push({
      cls: "sys", who: "Events", tip: TIP.events, line: `${esc(cap1(listJoin([...new Set(names)])))}.`,
      why: other.map((n) => `<div class="note">${esc(n.event.replaceAll("_", " "))}${eventDetail(n)}</div>`).join("")
        + g.llm_failures.map((f) => `<div class="note">LLM call failed (${esc(f.role)}): ${esc(f.error)}</div>`).join(""),
    });
  }
  return rows;
}

function chiefLine(c) {
  const names = (fs) => listJoin(fs.map((f) => PLAIN[f.name] || f.name));
  const out = [];
  if (c.promote_cid) out.push(`Sends design <code>${esc(c.promote_cid)}</code> to ${esc(SOLVER[c.fidelity] || c.fidelity)} to check the fast estimate.`);
  else if (c.mode === "inner_optimizer") out.push(`Hands ${esc(names(c.focus) || "a few parameters")} to Optuna, a numerical optimizer, for a quick search.`);
  else {
    const moves = c.focus.filter((f) => f.direction === "+" || f.direction === "-").map((f) => `${f.direction === "+" ? "more" : "less"} ${PLAIN[f.name] || f.name}`);
    const free = c.focus.filter((f) => f.direction !== "+" && f.direction !== "-");
    if (moves.length) out.push(`Asks for ${listJoin(moves)}${free.length ? `, with ${names(free)} free to move` : ""}.`);
    else if (free.length) out.push(`Lets the CAD agent move ${names(free)}.`);
    else out.push("Plans the next step.");
  }
  if (c.declare_plateau) out.push("Declares a plateau.");
  if (c.screen_override) out.push("Overrides the stall screen.");
  return out.join(" ");
}

/* "raised angle 7.58 → 7.97°" for each change of an attempt, against the parent's values. */
function changeList(a, parentP) {
  return a.changes.map((x) => {
    const old = parentP ? parentP[x.name] : null;
    const dir = old == null ? "set" : x.new_value > old ? "raised" : x.new_value < old ? "lowered" : "kept";
    return `${dir} ${PLAIN[x.name] || x.name}${old != null ? ` ${pval(x.name, old)} → ${pval(x.name, x.new_value)}${unitOf(x.name)}` : ""}`;
  });
}
const rejectWhy = (a) => (/^duplicate/.test(a.rejection || "") ? "it repeated a design already tested"
  : /^(bounds|trust_region|direction|not_allowed|unknown_param|no_change)/.test(a.rejection || "") ? "it broke the Chief's limits"
  : "it broke a geometry or rulebook check");
/* What changed between two recorded designs (the step code evaluates when every CAD proposal was rejected). */
function diffList(oldP, newP) {
  if (!oldP || !newP) return [];
  return S.run.free_params.filter((n) => n in oldP && n in newP && pval(n, oldP[n]) !== pval(n, newP[n]))
    .map((n) => `${newP[n] > oldP[n] ? "raised" : "lowered"} ${PLAIN[n] || n} ${pval(n, oldP[n])} → ${pval(n, newP[n])}${unitOf(n)}`);
}
const codeFallback = (g) => g.notes.some((n) => n.event === "cad_fallback") || /^deterministic fallback/.test(headOf(g)?.rationale || "");
const acceptedOf = (g) => g.cad.find((a) => a.outcome === "accepted") || (g.cad.length && g.cad[g.cad.length - 1].outcome !== "rejected" ? g.cad[g.cad.length - 1] : null);

function cadLine(g, parentP) {
  const acc = acceptedOf(g), rejected = g.cad.filter((a) => a.outcome === "rejected");
  const why = [...new Set(rejected.map(rejectWhy))].join("; ");
  let s = acc ? `${cap1(listJoin(changeList(acc, parentP)))}.` : "";
  if (rejected.length) {
    s += acc ? ` Code rejected ${rejected.length === 1 ? "an earlier proposal" : `${rejected.length} earlier proposals`} (${why}).`
      : `Code rejected ${rejected.length === 1 ? "its proposal" : `all ${rejected.length} proposals`} (${why}).`;
  }
  if (!acc && codeFallback(g)) {
    const fb = diffList(parentP, headOf(g)?.params);
    s += ` Code made the step itself${fb.length ? `: ${listJoin(fb)}` : ""}.`;
  }
  const dis = acc?.disagreements || [];
  if (dis.length) s += ` Overruled the Chief on ${listJoin(dis.map((d) => PLAIN[d.param] || d.param))}.`;
  return esc(s.trim());
}

function cadWhy(g, parentP) {
  return g.cad.map((a, k) => {
    const rejected = a.outcome === "rejected";
    const head = g.cad.length > 1 ? `attempt ${k + 1}${rejected ? " · rejected" : a.outcome ? " · accepted" : ""}` : rejected ? "rejected" : "";
    const ch = a.changes.map((x) => {
      const old = parentP ? parentP[x.name] : null;
      const dis = (a.disagreements || []).find((d) => d.param === x.name);
      return `<div class="change"><div class="pv">${esc(SHORT[x.name] || x.name)} ${old != null ? `${pval(x.name, old)} <span class="arrow">→</span> ` : "→ "}${pval(x.name, x.new_value)} <span class="arrow">${esc(PARAM_META[x.name]?.unit || "")}</span></div>
        <div class="mech">${esc(x.mechanism)}</div>
        ${x.override_reason ? `<div class="override"><b>Overrides the Chief${dis ? ` (Chief ${dirArrow(dis.chief)}, CAD ${dirArrow(dis.cad)})` : ""}:</b> ${esc(x.override_reason)}</div>` : ""}</div>`;
    }).join("");
    return `<div class="attempt ${rejected ? "rejected" : ""}">${head ? `<div class="att">${esc(head)}</div>` : ""}${ch}
      ${a.note ? `<div class="note">${esc(a.note)}</div>` : ""}
      ${a.rejection ? `<div class="rej">✕ ${esc(a.rejection)}</div>` : ""}</div>`;
  }).join("");
}

/* Why a result is not a pass, in a few words (from the ledger's numbers and failed check names). */
function shortWhy(ev, spec) {
  if (ev.passing) return "Passes.";
  if (ev.verdict && !["PASS", "TARGET_MISS"].includes(ev.verdict)) return `Rejected as ${ev.verdict.replaceAll("_", " ").toLowerCase()}.`;
  const off = ev.cl - spec.target_cl, fc = new Set(ev.failed_checks || []), why = [];
  if (Math.abs(off) > spec.cl_tol) why.push(off > 0 ? `${Math.abs(off).toFixed(3)} short of the target Cl` : `${Math.abs(off).toFixed(3)} past the target band`);
  if (ev.cd > spec.cd_max) why.push("too much drag");
  if (fc.has("neuralfoil_screen") || fc.has("stall_margin")) why.push("fails the stall check");
  if (fc.has("te_separation")) why.push("flow separates before the trailing edge");
  if (!why.length) return ev.solver === "neuralfoil" ? "In the target box; only XFoil can confirm it." : "Not a pass yet.";
  return `Not a pass: ${listJoin(why)}.`;
}

function solverLine(g) {
  const ev = headOf(g), n = g.evals.length;
  const res = `${SOLVER[ev.solver] || ev.solver}${ev.solver_level ? ` (recovery level ${ev.solver_level})` : ""}: Cl ${clTxt(ev.cl)}, Cd ${cdTxt(ev.cd)}.`;
  return esc(`${n > 1 ? `Best of ${n} evaluations, ` : ""}${res} ${shortWhy(ev, S.run.spec)}`);
}

function solverWhy(g) {
  const solves = g.evals.map((e) => `<div class="solve">${esc(e.cid)} · ${esc(SOLVER[e.solver] || e.solver)}${e.inner_optimizer ? " (inner)" : ""} · Cl ${clTxt(e.cl)} · Cd ${cdTxt(e.cd)} · ${esc(statusOf(e).text)}</div>`
    + (e.failing.length && !e.inner_optimizer ? `<ul class="ev">${e.failing.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : ""));
  return solves.length > 6 ? solves.slice(0, 6).join("") + `<div class="note">+ ${solves.length - 6} more evaluations</div>` : solves.join("");
}

function criticLine(g) {
  const cr = g.critic;
  const status = cr.status === "PASS" ? "pass" : String(cr.status || "").replaceAll("_", " ").toLowerCase();
  if (g.critic_source === "numeric") return esc(`No LLM text (the call failed); the numeric verdict is ${status}.`);
  const sym = cr.symptom && cr.symptom !== "NONE" ? SYMPTOM[cr.symptom] || cr.symptom.replaceAll("_", " ").toLowerCase() : "no problem found";
  return esc(`${cap1(status)}: ${sym}${cr.confidence != null ? ` (confidence ${cr.confidence})` : ""}.`);
}

function eventDetail(n) {
  if (n.event === "screen_xfoil_disagreement" && n.stall) {
    const s = n.stall, v = (x) => (x == null ? "—" : `${Number(x).toFixed(3)}/°`);
    return `: stall slope NeuralFoil ${esc(v(s.screen_dcl_dalpha))} (${s.screen_ok ? "ok" : "fails"}), XFoil ${esc(v(s.xfoil_dcl_dalpha))} (${s.xfoil_ok ? "ok" : "fails"})`;
  }
  return `${n.reason ? `: ${esc(n.reason)}` : ""}${n.error ? `: ${esc(n.error)}` : ""}${n.action ? `: ${esc(n.action)}` : ""}`;
}

/* ------------------------------------------------------------------ polar */
const PC = { l: 58, r: 16, t: 12, b: 36 };
function drawPolar() {
  const svg = $("#polar");
  const rect = svg.getBoundingClientRect();
  const W = Math.max(280, rect.width), H = Math.max(180, rect.height);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = "";
  const r = S.run, s = r.spec;
  const all = r.generations.flatMap((g) => g.evals).filter((e) => e.cl != null && e.cd != null);
  if (!all.length) all.push({ cl: s.target_cl, cd: s.cd_max * 0.7 }); // empty live run: frame the target box
  const b = r.baseline && r.baseline.cl != null ? r.baseline : null;
  const cds = all.map((e) => e.cd).concat([s.cd_max], b ? [b.cd] : []);
  const cls = all.map((e) => e.cl).concat([s.target_cl - s.cl_tol, s.target_cl + s.cl_tol], b ? [b.cl] : []);
  let xmin = Math.min(...cds), xmax = Math.max(...cds), ymin = Math.min(...cls), ymax = Math.max(...cls);
  const px = (xmax - xmin) * 0.08 || 0.001, py = (ymax - ymin) * 0.08 || 0.01;
  xmin -= px; xmax += px; ymin -= py; ymax += py;
  const X = (cd) => PC.l + ((cd - xmin) / (xmax - xmin)) * (W - PC.l - PC.r);
  const Y = (cl) => PC.t + ((cl - ymin) / (ymax - ymin)) * (H - PC.t - PC.b); // more negative Cl (downforce) on top

  // grid + ticks
  const nice = (lo, hi, n) => {
    const step0 = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= step0);
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-12; v += step) out.push(+v.toFixed(10));
    return { ticks: out, step };
  };
  const xt = nice(xmin, xmax, Math.max(3, Math.floor(W / 110)));
  const yt = nice(ymin, ymax, Math.max(3, Math.floor(H / 55)));
  const g = el("g", {}, svg);
  for (const v of xt.ticks) {
    el("line", { class: "gridl", x1: X(v), x2: X(v), y1: PC.t, y2: H - PC.b }, g);
    const t = el("text", { class: "tick", x: X(v), y: H - PC.b + 14, "text-anchor": "middle" }, g);
    t.textContent = v.toFixed(Math.max(0, -Math.floor(Math.log10(xt.step))));
  }
  for (const v of yt.ticks) {
    el("line", { class: "gridl", x1: PC.l, x2: W - PC.r, y1: Y(v), y2: Y(v) }, g);
    const t = el("text", { class: "tick", x: PC.l - 6, y: Y(v) + 3.5, "text-anchor": "end" }, g);
    t.textContent = (v < 0 ? "−" : "") + Math.abs(v).toFixed(Math.max(0, -Math.floor(Math.log10(yt.step))));
  }
  el("line", { class: "axis", x1: PC.l, x2: W - PC.r, y1: H - PC.b, y2: H - PC.b }, g);
  el("line", { class: "axis", x1: PC.l, x2: PC.l, y1: PC.t, y2: H - PC.b }, g);
  const xl = el("text", { class: "ax-label", x: (PC.l + W - PC.r) / 2, y: H - 4, "text-anchor": "middle" }, g);
  xl.textContent = "Cd (drag) →";
  const yl = el("text", { class: "ax-label", x: 12, y: (PC.t + H - PC.b) / 2, "text-anchor": "middle", transform: `rotate(-90 12 ${(PC.t + H - PC.b) / 2})` }, g);
  yl.textContent = "Cl  (downforce ↑)";

  // target box: |Cl - target| <= tol and Cd <= cd_max
  const bx0 = X(Math.max(xmin, 0)), bx1 = X(s.cd_max), by0 = Y(s.target_cl - s.cl_tol), by1 = Y(s.target_cl + s.cl_tol);
  el("rect", { class: "box", x: Math.min(bx0, bx1), y: by0, width: Math.abs(bx1 - bx0), height: by1 - by0, rx: 3 }, g);
  const bl = el("text", { class: "box-label", x: Math.min(bx0, bx1) + 6, y: by0 + 14 }, g); // inside, at the empty low-drag end
  bl.textContent = "target box";

  // trail through the headline record of each generation so far
  const shown = S.frames.slice(0, S.fi + 1);
  const trail = shown.map((f) => headOf(f)).filter((e) => e.cl != null && e.cd != null);
  if (trail.length) el("path", { class: "trail", d: "M" + trail.map((e) => `${X(e.cd).toFixed(1)} ${Y(e.cl).toFixed(1)}`).join("L") }, g);

  // Optuna's best / closest design
  if (b) {
    const ox = X(b.cd), oy = Y(b.cl), d = 7;
    el("path", { class: "opt", d: `M${ox} ${oy - d}L${ox + d} ${oy}L${ox} ${oy + d}L${ox - d} ${oy}Z` }, g);
  }

  const pts = [];
  shown.forEach((f, k) => f.evals.forEach((e) => { if (e.cl != null && e.cd != null) pts.push({ e, g: f, cur: k === S.fi && e === headOf(f) }); }));
  const color = KIND_COLOR;
  for (const p of pts) {
    const x = X(p.e.cd), y = Y(p.e.cl), st = statusOf(p.e);
    const attrs = { class: `pt ${p.e.inner_optimizer ? "inner" : ""}`, fill: color[st.kind] };
    if (p.e.solver === "neuralfoil") el("circle", { ...attrs, cx: x, cy: y, r: p.e.inner_optimizer ? 3.5 : 5 }, g);
    else el("rect", { ...attrs, x: x - 5.5, y: y - 5.5, width: 11, height: 11, rx: 1.5 }, g);
    if (p.cur) el("circle", { class: "cur", cx: x, cy: y, r: 10 }, g);
  }
  // hit layer + tooltip
  const tip = $("#tip");
  for (const p of pts) {
    const h = el("circle", { class: "hit", cx: X(p.e.cd), cy: Y(p.e.cl), r: 11 }, g);
    h.addEventListener("pointerenter", () => {
      const st = statusOf(p.e);
      tip.innerHTML = `<div class="r"><span>gen ${p.g.gen}</span><span>${esc(p.e.cid)}</span></div>
        <div class="r"><span>solver</span><span>${esc(SOLVER[p.e.solver] || p.e.solver)}${p.e.inner_optimizer ? " (inner)" : ""}</span></div>
        <div class="r"><span>Cl</span><span>${clTxt(p.e.cl)}</span></div><div class="r"><span>Cd</span><span>${cdTxt(p.e.cd)}</span></div>
        <div class="r"><span>status</span><span>${esc(st.text)}</span></div>
        ${p.e.failing[0] ? `<div style="margin-top:4px;color:var(--ink-3);max-width:260px">${esc(p.e.failing[0])}</div>` : ""}`;
      tip.hidden = false;
      const x = X(p.e.cd), y = Y(p.e.cl);
      tip.style.left = `${Math.min(x + 14, W - 270)}px`;
      tip.style.top = `${Math.max(4, y - 30)}px`;
    });
    h.addEventListener("pointerleave", () => (tip.hidden = true));
    h.addEventListener("click", () => { setPlaying(false); goTo(S.frames.indexOf(p.g)); });
  }
  renderLegend(all, !!b);
}

// Point colours. A miss stays grey so the few designs that passed something stand out.
const KIND_COLOR = { pass: "var(--good)", screen: "var(--warning)", miss: "var(--ghost)", fail: "var(--critical)", "": "var(--ghost)" };
const KIND_LABEL = { pass: "passed", screen: "passed NeuralFoil only", miss: "missed the target", fail: "failed a check" };

/* Only what this run has: kinds of result, solvers, and Optuna's closest design when there is one. */
function renderLegend(evals, hasOpt) {
  const kinds = new Set(evals.map((e) => statusOf(e).kind)), solvers = new Set(evals.map((e) => e.solver));
  const dot = (c) => `<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="${c}"/></svg>`;
  const ring = '<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.5" fill="none" stroke="var(--ink-2)" stroke-width="1.5"/></svg>';
  const square = '<svg viewBox="0 0 12 12"><rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="var(--ink-2)" stroke-width="1.5"/></svg>';
  const diamond = '<svg viewBox="0 0 12 12"><path d="M6 1L11 6L6 11L1 6Z" fill="none" stroke="var(--ink-2)" stroke-width="1.5"/></svg>';
  $("#polar-legend").innerHTML = [
    ...["pass", "screen", "miss", "fail"].filter((k) => kinds.has(k)).map((k) => `<span>${dot(KIND_COLOR[k])}${KIND_LABEL[k]}</span>`),
    solvers.has("neuralfoil") ? `<span>${ring}NeuralFoil</span>` : "",
    solvers.has("xfoil") ? `<span>${square}XFoil</span>` : "",
    hasOpt ? `<span>${diamond}Optuna's closest</span>` : "",
  ].join("");
}

/* ------------------------------------------------------------------ controls */
function wireControls() {
  $("#watch").onclick = watchReplay;
  $("#hero-live").onclick = openLivePanel;
  $("#reasoning-toggle").onclick = () => setReasoning(!S.reasoning);
  $("#btn-play").onclick = () => setPlaying(!S.playing);
  $("#btn-prev").onclick = () => { setPlaying(false); goTo(S.fi - 1); };
  $("#btn-next").onclick = () => { setPlaying(false); goTo(S.fi + 1); };
  $("#btn-morph").onclick = toggleMorph;
  $("#scrubber").addEventListener("input", (e) => { setPlaying(false); goTo(Number(e.target.value), { instant: true }); });
  for (const b of document.querySelectorAll(".speed button")) b.onclick = () => setSpeed(Number(b.dataset.speed));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, select, textarea, .dial svg") || !$("#intro").hidden) return;
    if (e.key === " " && e.target.closest("button, summary, a")) return; // space presses the focused control
    if (e.key === " ") { e.preventDefault(); setPlaying(!S.playing); }
    if (e.key === "ArrowRight") { setPlaying(false); goTo(S.fi + 1); }
    if (e.key === "ArrowLeft") { setPlaying(false); goTo(S.fi - 1); }
  });
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { layoutStage(); drawPolar(); }, 80); });
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("aeroswarm-theme"); } catch (_) { /* storage unavailable */ }
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme-toggle").onclick = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("aeroswarm-theme", next); } catch (_) { /* ignore */ }
  };
}

/* ------------------------------------------------------------------ plain-language layer */
// Everything here is generated from the export's facts (ledger numbers, check names, which agent acted).
// It never paraphrases agent text: the agents' own words stay verbatim in the feed.
const TIP = {
  chief: "Chief aerodynamicist (LLM). Reads the results so far and decides the next move: which shape parameters to change and in which direction, or which design to verify with the accurate solver.",
  cad: "CAD engineer (LLM). Turns the Chief's plan into concrete numbers for camber, camber position, thickness and angle, and explains the physics. It may overrule the Chief, but must say why. Code checks every proposal against the rules.",
  solver: "Physics solvers, not an LLM. NeuralFoil is a fast neural-network airfoil model used for exploring; XFoil is the slower, more accurate panel code that must confirm a design before it can pass.",
  critic: "Critic (LLM). An independent reviewer that sees the solver output and the automatic checks, and diagnoses what is wrong. It can downgrade a result but never upgrade one.",
  parent: "The design this generation starts from: the best one so far, picked by code (smallest violation of the targets).",
  cl: "Lift coefficient. Negative means downforce (the wing is upside down). The target is a band around one value: too little or too much both miss.",
  cd: "Drag coefficient. Must stay at or below the cap; more drag costs straight-line speed.",
  solverRo: "Which solver produced these numbers. NeuralFoil: fast estimate. XFoil: accurate check; only XFoil can produce a final pass. L0–L3 is XFoil's recovery level if it had trouble converging.",
  stall: "Stall margin: how much extra downforce the wing still gains if the angle increases by 1–2°. Near zero or negative means it is about to stall (flow separating), so a gust or a bump would cost downforce. NF = NeuralFoil screen, XF = measured by XFoil.",
  polar: "Each dot is one evaluated design: drag to the right, downforce up. The green box is the target. Circles are NeuralFoil estimates, squares are XFoil checks; the ring marks the current generation.",
  dials: "The four shape parameters of the wing section (a NACA 4-digit profile): how curved it is (camber), where the curve peaks, how thick it is, and its angle to the airflow.",
  target: "What the team must reach: a downforce coefficient within the band, drag at or under the cap, a healthy stall margin, inside the racing rulebook's geometry limits, and confirmed by XFoil.",
  feed: "One line per step of this generation, written by code from the run's records. “Show reasoning” adds each agent's own words, quoted from the trace log (long text shortened, never reworded).",
  optuna: "Optuna TPE, a numerical optimizer (no LLM). The Chief can hand it a few parameters for a quick search under the same checks; the best result is shown.",
  events: "Notable things the code recorded in this generation, such as solver disagreements, recoveries or failed LLM calls.",
};
const SYMPTOM = {
  TE_SEPARATION_MAIN: "flow separating near the trailing edge",
  TE_SEPARATION_FLAP: "flow separating on the flap",
  LE_SUCTION_SPIKE: "a sharp suction spike at the leading edge",
  SLOT_CHOKED: "a choked slot",
  EARLY_STALL: "the wing is close to stalling",
  INSUFFICIENT_LOADING: "not enough downforce",
  EXCESS_PRESSURE_DRAG: "too much pressure drag",
  NONE: "no problem found",
};
const PLAIN = { main_camber: "camber", main_camber_pos: "camber position", main_thickness: "thickness", alpha_deg: "angle" };
const unitOf = (n) => (PARAM_META[n]?.unit === "deg" ? "°" : "%");

function verdictSentence(ev, spec) {
  const off = ev.cl - spec.target_cl;
  const inCl = Math.abs(off) <= spec.cl_tol, inCd = ev.cd <= spec.cd_max;
  const fc = new Set(ev.failed_checks || []);
  const solver = ev.solver === "neuralfoil" ? "NeuralFoil estimates" : `${SOLVER[ev.solver] || ev.solver} measures`;
  let s = `${solver} Cl <b>${clTxt(ev.cl)}</b> and Cd <b>${cdTxt(ev.cd)}</b>: `;
  const why = [];
  if (!inCl) why.push(off > 0 ? `${Math.abs(off).toFixed(3)} short of the downforce target` : `${Math.abs(off).toFixed(3)} more downforce than the target band allows`);
  if (!inCd) why.push("too much drag");
  if (fc.has("neuralfoil_screen") || fc.has("stall_margin")) why.push("it fails the stall check (too close to stalling)");
  if (fc.has("te_separation")) why.push("the flow separates before the trailing edge");
  if (ev.passing) return s + `inside the target box with a healthy stall margin, confirmed by XFoil. <b>This design passes.</b>`;
  if (ev.verdict && !["PASS", "TARGET_MISS"].includes(ev.verdict)) return s + `the result was rejected as ${ev.verdict.replaceAll("_", " ").toLowerCase()}.`;
  if (!why.length && ev.solver === "neuralfoil") return s + `inside the target box. Only XFoil can confirm it, so it needs a verification run.`;
  if (!why.length) return s + "not a pass yet.";
  return s + (inCl && inCd ? "inside the target box, but " : "") + why.join(", and ") + ".";
}

function narrate(g) {
  const r = S.run, ev = headOf(g), spec = r.spec, out = [];
  const c = g.chief;
  if (g.gen === 0 || !g.parent && !g.cad.length && !(c && c.promote_cid) && ev.rationale === "baseline") {
    const p = ev.params;
    out.push(`<b>Start.</b> The team evaluates the starting wing (camber ${pval("main_camber", p.main_camber)}%, thickness ${pval("main_thickness", p.main_thickness)}%, angle ${pval("alpha_deg", p.alpha_deg)}°).`);
  } else if (ev.solver !== "neuralfoil" && /^promotion of/.test(ev.rationale || "")) {
    out.push(`<b>Verification.</b> The Chief sends design <code>${esc(ev.cid)}</code> to ${esc(SOLVER[ev.solver] || ev.solver)}, the accurate solver, to check the fast estimate.`);
  } else if (g.evals.some((e) => e.inner_optimizer)) {
    const n = g.evals.filter((e) => e.inner_optimizer).length;
    out.push(`<b>Search.</b> The Chief hands ${esc((c?.focus || []).map((f) => PLAIN[f.name] || f.name).join(", ") || "a few parameters")} to Optuna, a numerical optimizer (no LLM), for ${n} quick evaluations. Shown: the best of them.`);
  } else {
    const acc = acceptedOf(g);
    const parentP = S.cidParams[ev.parent_cid] || null;
    const rejected = g.cad.filter((a) => a.outcome === "rejected");
    const why = [...new Set(rejected.map(rejectWhy))].join("; ");
    if (acc) {
      const ch = changeList(acc, parentP);
      const rej = rejected.length ? ` (Code rejected ${rejected.length === 1 ? "its first proposal" : `${rejected.length} earlier proposals`}: ${why}.)` : "";
      const dis = acc.disagreements || [];
      const ovr = dis.length ? ` It <b>overruled the Chief</b> on ${dis.map((d) => PLAIN[d.param] || d.param).join(", ")}; its reason is under “Show reasoning”.` : "";
      out.push(`<b>Change.</b> The CAD agent ${ch.join(", ")}.${rej}${ovr}`);
    } else if (rejected.length) {
      // every proposal was rejected: describe the design actually evaluated, not a rejected proposal
      const fb = codeFallback(g) ? diffList(parentP, ev.params) : [];
      out.push(`<b>Change.</b> Code rejected ${rejected.length === 1 ? "the CAD agent's proposal" : `all ${rejected.length} CAD proposals`} (${why})${codeFallback(g) ? ` and made the step itself${fb.length ? `: ${fb.join(", ")}` : ""}` : ""}.`);
    }
  }
  out.push(verdictSentence(ev, spec));
  if (g.critic && g.critic_source === "llm" && g.critic.symptom && g.critic.symptom !== "NONE" && !ev.passing)
    out.push(`The Critic's diagnosis: ${SYMPTOM[g.critic.symptom] || g.critic.symptom.toLowerCase()}.`);
  return out.join(" ");
}

/* One floating tooltip for every [data-tip] element (hover or keyboard focus). */
function wireTips() {
  const tip = document.createElement("div");
  tip.className = "gtip";
  tip.hidden = true;
  tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);
  const show = (t) => {
    tip.textContent = t.dataset.tip;
    tip.hidden = false;
    const b = t.getBoundingClientRect(), w = Math.min(320, window.innerWidth - 24);
    tip.style.width = `${w}px`;
    const left = Math.max(12, Math.min(b.left + b.width / 2 - w / 2, window.innerWidth - w - 12));
    const below = b.bottom + 8 + tip.offsetHeight < window.innerHeight;
    tip.style.left = `${left}px`;
    tip.style.top = `${below ? b.bottom + 8 : b.top - tip.offsetHeight - 8}px`;
  };
  const hide = () => (tip.hidden = true);
  document.addEventListener("pointerover", (e) => { const t = e.target.closest("[data-tip]"); if (t) show(t); });
  document.addEventListener("pointerout", (e) => { if (e.target.closest("[data-tip]")) hide(); });
  document.addEventListener("focusin", (e) => { const t = e.target.closest("[data-tip]"); if (t) show(t); });
  document.addEventListener("focusout", hide);
  document.addEventListener("scroll", hide, true);
  for (const el2 of document.querySelectorAll("[data-tip-key]")) {
    el2.dataset.tip = TIP[el2.dataset.tipKey];
    if (!el2.hasAttribute("tabindex") && !/^(BUTTON|INPUT|SELECT)$/.test(el2.tagName)) el2.tabIndex = 0;
  }
}

/* "How to read this": opened with the ? button (or ?intro=1). Filled from the run's own spec. */
function openIntro() {
  const r = S.run, s = r?.spec;
  const box = $("#intro");
  if (s) {
    $("#intro-target").innerHTML = `Cl <b>${clTxt(s.target_cl)} ± ${s.cl_tol}</b> (downforce), Cd <b>≤ ${s.cd_max}</b> (drag), a healthy stall margin, inside the ${esc(s.rulebook)} geometry rules, confirmed by XFoil. Budget: ${s.max_evals} evaluations.`;
  }
  $("#intro-live").hidden = !S.live.available;
  box.hidden = false;
  $("#intro-go").focus();
}
function closeIntro(play = true) {
  $("#intro").hidden = true;
  if (play) watchReplay();
}
function wireIntro() {
  $("#help").onclick = () => { setPlaying(false); openIntro(); };
  $("#intro-go").onclick = () => closeIntro(true);
  $("#intro-close").onclick = () => closeIntro(false);
  $("#intro-live").onclick = () => { closeIntro(false); openLivePanel(); };
  $("#intro").addEventListener("click", (e) => { if (e.target.id === "intro") closeIntro(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#intro").hidden) closeIntro(false); });
}
/* The live-run panel lives in the closed Details section: open it and bring the panel into view. */
function openLivePanel() {
  $("#details").open = true;
  $("#live").scrollIntoView({ behavior: smooth(), block: "center" });
  $("#live-go").focus({ preventScroll: true });
}

/* ------------------------------------------------------------------ live mode (local server only) */
// The page offers live runs only when it is served by `python -m swarm.live` (api/health answers). The stream
// carries the same per-generation records as a recorded export; when the run ends it is saved to the gallery.
S.live = { startOk: null, available: false, health: null, runId: null, es: null, running: false, attached: false, gens: new Set(), progress: "" };
const liveRunning = () => S.live.running && S.live.attached;

async function probeLive() {
  let h = null;
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 1500);
    const r = await fetch(`${API}api/health`, { signal: ctl.signal, cache: "no-cache" });
    clearTimeout(t);
    if (r.ok && (r.headers.get("content-type") || "").includes("json")) h = await r.json();
  } catch (_) { /* no server: recorded replays only */ }
  if (!h || !h.ok) return;
  S.live.available = true;
  S.live.health = h;
  if (API) { // the server's gallery includes finished live runs; its files are served from there
    try { S.index = await fetchJSON(`${API}runs/index.json`); S.dataBase = API; fillSelect(); } catch (_) { /* keep the static one */ }
  }
  $("#live-code-row").hidden = !h.access_code_required;
  try { $("#live-code").value = sessionStorage.getItem("aeroswarm-code") || ""; } catch (_) { /* optional */ }
  $("#live").hidden = false;
  $("#intro-live").hidden = false;
  $("#hero-live").hidden = false;
  $("#details-hint").textContent = "Start design, live run, target, run facts, Optuna comparison, CAD files";
  const sel = $("#live-model");
  sel.innerHTML = Object.entries(h.models)
    .filter(([, per]) => per != null)
    .map(([m, per]) => `<option value="${esc(m)}">${esc(m)} (≈$${per.toFixed(3)}/eval)</option>`).join("");
  sel.value = h.defaults.model;
  $("#live-evals").value = h.defaults.max_evals;
  $("#live-evals").max = h.caps.max_evals;
  $("#live-budget").value = h.defaults.budget_usd;
  $("#live-budget").max = h.caps.budget_usd;
  $("#live-inner").checked = h.defaults.inner_optimizer;
  $("#live-llm").value = h.anthropic_key ? "anthropic" : "mock";
  for (const id of ["#live-llm", "#live-model", "#live-evals", "#live-budget", "#live-code"]) $(id).addEventListener("input", liveEstimate);
  $("#live-go").onclick = startLiveRun;
  liveEstimate();
  checkLiveStart();
  if (h.busy) { liveStatus(`Run ${h.busy} is in progress on the server.`, "Watch it", () => attachLive(h.busy)); }
}

function liveEstimate() {
  const h = S.live.health;
  const mock = $("#live-llm").value === "mock";
  $("#live-model").disabled = mock;
  const evals = Number($("#live-evals").value), cap = Number($("#live-budget").value);
  const per = h.models[$("#live-model").value];
  const go = $("#live-go");
  if (!mock && !h.anthropic_key) {
    $("#live-est").textContent = "No Anthropic API key on the server: set AEROSWARM_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY and restart it, or use the mock.";
    go.disabled = true;
    return;
  }
  const needCode = !mock && h.access_code_required && !$("#live-code").value.trim();
  go.disabled = S.live.running || S.live.startOk === false || needCode;
  const left = h.daily ? Math.max(0, h.daily.cap_usd - h.daily.spent_usd) : null;
  $("#live-est").innerHTML = mock
    ? `Free. The mock is a rule-based stand-in, <b>not an LLM</b>; the run is labelled as such.`
    : `Estimated ≈ <b>$${Math.min(cap, per * evals).toFixed(2)}</b>; stops at <b>$${cap.toFixed(2)}</b> or ${evals} evaluations, whichever comes first. Target Cl ${clTxt(h.spec.target_cl)} ± ${h.spec.cl_tol}, Cd ≤ ${h.spec.cd_max}.` +
      (left != null ? ` Today's live budget: $${left.toFixed(2)} of $${h.daily.cap_usd.toFixed(2)} left.` : "") +
      (needCode ? ` <b>Enter the access code</b> to run Claude (the mock needs none).` : "");
  if (h.xfoil === false) $("#live-est").innerHTML += ` <b>XFoil is not installed on this server</b>, so designs cannot be verified and no run can pass.`;
}

/* Ask the server whether the dial-set start passes the run's geometry and rule checks (debounced). */
function checkLiveStart() {
  if (!S.live.available) return;
  clearTimeout(S.live.checkT);
  S.live.checkT = setTimeout(async () => {
    const h = S.live.health;
    const start = Object.fromEntries(Object.keys(h.bounds).map((k) => [k, Number((S.pick[k] ?? S.run.start[k]).toFixed(4))]));
    let out = null;
    try {
      const r = await fetch(`${API}api/check`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ start }) });
      out = await r.json();
      if (!r.ok) out = { ok: false, violations: [typeof out.detail === "string" ? out.detail : "invalid start"] };
    } catch (_) { return; }
    S.live.startOk = out.ok;
    const box = $("#live-check");
    box.className = `live-check ${out.ok ? "ok" : "bad"}`;
    box.textContent = out.ok
      ? `Start design passes the geometry and ${out.rulebook} checks.`
      : `These dials break the ${out.rulebook || "rule"} checks: ${out.violations[0].split(" (")[0].split("; increase")[0]}${out.violations.length > 1 ? ` (+${out.violations.length - 1} more)` : ""}. `;
    box.title = out.ok ? "" : out.violations.join("\n");
    if (!out.ok && h.default_start) {
      const b = document.createElement("button");
      b.className = "more";
      b.textContent = "Use the preset start";
      b.onclick = () => { S.pick = { ...h.default_start }; updateDials(S.pick); renderNearest(); checkLiveStart(); };
      box.appendChild(b);
    }
    liveEstimate();
  }, 250);
}

function liveStatus(text, action, fn) {
  const box = $("#live-status");
  box.innerHTML = esc(text) + (action ? ` <button class="more" id="live-act">${esc(action)}</button>` : "");
  if (action) $("#live-act").onclick = fn;
}

async function startLiveRun() {
  const h = S.live.health;
  const body = {
    start: Object.fromEntries(Object.keys(h.bounds).map((k) => [k, Number((S.pick[k] ?? S.run.start[k]).toFixed(4))])),
    max_evals: Number($("#live-evals").value),
    budget_usd: Number($("#live-budget").value),
    llm: $("#live-llm").value,
    model: $("#live-model").value,
    inner_optimizer: $("#live-inner").checked,
    access_code: $("#live-code").value.trim(),
  };
  try { sessionStorage.setItem("aeroswarm-code", body.access_code); } catch (_) { /* optional */ }
  $("#live-go").disabled = true;
  liveStatus("Starting…");
  let r, out;
  try {
    r = await fetch(`${API}api/runs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    out = await r.json();
  } catch (e) {
    liveStatus(`Could not reach the server (${e.message}).`);
    liveEstimate();
    return;
  }
  if (!r.ok) {
    const msg = typeof out.detail === "string" ? out.detail : JSON.stringify(out.detail);
    liveStatus(`Not started: ${msg}`);
    liveEstimate();
    return;
  }
  S.live.token = out.control_token;
  attachLive(out.run_id, { own: true });
  $("#main-view").scrollIntoView({ behavior: smooth(), block: "start" });
}

function attachLive(runId, { own = false } = {}) {
  detachLive();
  setPlaying(false);
  S.live.runId = runId;
  S.live.running = true;
  S.live.attached = true;
  S.live.gens = new Set();
  S.live.progress = "";
  $("#live-go").disabled = true;
  if (!own) S.live.token = null; // watching someone else's run: only its starter can stop it
  const stop = $("#live-stop");
  stop.hidden = !S.live.token;
  stop.disabled = false;
  stop.textContent = "Stop run";
  stop.onclick = () => stopLiveRun(runId);
  showNow("Starting the run…");
  const chip = $("#source-chip");
  chip.textContent = "Live run";
  chip.classList.add("live");
  const es = new EventSource(`${API}api/runs/${encodeURIComponent(runId)}/stream`);
  S.live.es = es;
  es.addEventListener("run", (e) => {
    if (S.run && S.run.run_id === runId && S.live.gens.size) return; // reconnect: keep what is on screen
    const head = JSON.parse(e.data);
    setRun({ ...head, generations: [], baseline: null }, { keepPick: true });
    S.live.budget = head.budget_usd;
    $("#run-select").value = "";
  });
  es.addEventListener("generation", (e) => {
    const { generation: g, outlines } = JSON.parse(e.data);
    if (S.live.gens.has(g.gen)) return;
    S.live.gens.add(g.gen);
    addLiveGeneration(g, outlines);
  });
  es.addEventListener("progress", (e) => {
    const p = JSON.parse(e.data);
    showNow(p.finished ? "" : p.gen != null ? `Generation ${p.gen} in progress: ${p.phase.charAt(0).toLowerCase()}${p.phase.slice(1)}…` : `${p.phase}…`);
    const mm = Math.floor(p.elapsed_s / 60), ss = String(Math.floor(p.elapsed_s % 60)).padStart(2, "0");
    S.live.progress = `${p.evals} evaluations · $${p.cost_usd.toFixed(2)} of $${(S.live.budget ?? 0).toFixed(2)} · ${p.llm_calls} LLM calls · ${mm}:${ss}`;
    liveStatus(S.live.progress);
    if (liveRunning()) renderHero();
  });
  es.addEventListener("done", async (e) => {
    es.close();
    const final = JSON.parse(e.data);
    S.live.running = false;
    S.live.attached = false;
    const fi = S.fi;
    setRun(final, { keepPick: true });
    endLiveChip("Live run · saved to gallery");
    try { S.index = await fetchJSON(`${S.dataBase}runs/index.json`); fillSelect(); } catch (_) { /* gallery refresh is optional */ }
    const entry = S.index.runs.find((x) => x.name === final.name);
    if (entry) $("#run-select").value = entry.file;
    goTo(Math.min(fi, S.frames.length - 1), { instant: true });
    goTo(S.frames.length - 1);
    try { S.live.health = await (await fetch(`${API}api/health`, { cache: "no-cache" })).json(); } catch (_) { /* keep */ }
    liveStatus(`Finished: ${final.termination}, ${final.evals} evaluations${final.cost_usd != null ? `, est. $${final.cost_usd.toFixed(2)}` : ""}. Saved as ${final.name}.`);
    liveEstimate();
  });
  es.addEventListener("error", (e) => {
    if (e.data) { // a server-sent error event (the run failed), not a dropped connection
      es.close();
      S.live.running = false;
      endLiveChip("Live run · failed");
      const msg = JSON.parse(e.data).message;
      liveStatus(`The run stopped with an error: ${msg}`);
      if (S.run) { S.run._liveError = msg; renderHero(); }
      liveEstimate();
    }
  });
}

function addLiveGeneration(g, outlines) {
  const r = S.run;
  Object.assign(r.outlines, outlines);
  r.generations.push(g);
  for (const e of g.evals) S.cidParams[e.cid] ??= e.params;
  const following = !S.frames.length || S.fi === S.frames.length - 1;
  S.frames = r.generations.filter((x) => x.head >= 0);
  r.evals = r.generations.reduce((n, x) => n + x.evals.length, 0);
  layoutStage();
  $("#scrubber").max = Math.max(0, S.frames.length - 1);
  $("#gen-of").textContent = `of ${g.gen}`;
  if (following) goTo(S.frames.length - 1, { instant: S.frames.length === 1 });
  renderHero();
}

function detachLive() {
  if (S.live.es) S.live.es.close();
  S.live.es = null;
  if (S.live.running && S.live.attached) {
    const id = S.live.runId;
    S.live.attached = false;
    endLiveChip("Recorded run");
    $("#live-go").disabled = true;
    liveStatus(`Run ${id} keeps going on the server and joins the gallery when it ends.`, "Back to it", () => attachLive(id, { own: !!S.live.token }));
  }
}

async function stopLiveRun(runId) {
  const b = $("#live-stop");
  b.disabled = true;
  b.textContent = "Stopping…";
  try {
    const r = await fetch(`${API}api/runs/${encodeURIComponent(runId)}/stop`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: S.live.token || "" }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
  } catch (e) {
    b.disabled = false;
    b.textContent = "Stop run";
    liveStatus(`Could not reach the server to stop the run (${e.message}).`);
  }
}

function showNow(text) {
  $("#now").hidden = !text;
  $("#now-text").textContent = text || "";
}

function endLiveChip(text) {
  $("#live-stop").hidden = true;
  showNow("");
  const chip = $("#source-chip");
  chip.textContent = text;
  chip.classList.remove("live");
}

boot();
