/* AeroSwarm run viewer: replays exported runs (viewer/runs/*.json, written by scripts/export_run.py).
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
  open: new Set(), // feed cards the viewer expanded
  bannerDismissed: false,
  cidParams: {},
  cidOutline: {},
  dataBase: "", // where runs/*.json come from: this page's folder, or the live server's
};

/* ------------------------------------------------------------------ helpers */
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmt = (x, dp) => (x == null || !isFinite(x) ? "—" : Number(x).toFixed(dp));
const signed = (x, dp) => (x == null ? "—" : (x < 0 ? "−" : "+") + Math.abs(x).toFixed(dp));
const clTxt = (x) => (x == null ? "—" : (x < 0 ? "−" : "") + Math.abs(x).toFixed(4));
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
  if (!ev) return { cls: "", text: "—" };
  if (ev.passing) return { cls: "pass", text: "PASS" };
  const v = ev.verdict || ev.solver_status;
  if (v === "PASS") return { cls: "miss", text: `PASS at ${SOLVER[ev.solver] || ev.solver} only` };
  if (v === "TARGET_MISS") return { cls: "miss", text: "TARGET MISS" };
  return { cls: "fail", text: String(v || "FAILED").replaceAll("_", " ") };
}
const headOf = (g) => (g && g.head >= 0 ? g.evals[g.head] : null);
const dur = (ms) => ms / S.speed;

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
  const intro = !introSeen() && q.get("intro") !== "0";
  await loadRun(first.file, { autoplay: !intro && q.get("autoplay") !== "0", gen: q.get("gen") });
  if (intro) openIntro();
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
}

function fatal(html) {
  $("#feed").innerHTML = `<div class="card"><div class="card-body"><p>${html}</p></div></div>`;
}

async function loadRun(file, { autoplay = true, gen = null, keepPick = false } = {}) {
  const data = await fetchJSON(`${S.dataBase}runs/${file}`);
  $("#run-select").value = file;
  setRun(data, { keepPick });
  const startFi = gen != null ? Math.max(0, S.frames.findIndex((g) => g.gen >= Number(gen))) : 0;
  goTo(startFi, { instant: true });
  setPlaying(autoplay && S.frames.length > 1);
}

function setRun(data, { keepPick = false } = {}) {
  S.run = data;
  S.frames = data.generations.filter((g) => g.head >= 0);
  S.cidParams = {};
  for (const g of data.generations) for (const e of g.evals) S.cidParams[e.cid] ??= e.params;
  S.cidParams[data.start_cid] ??= data.start;
  S.cidOutline = data.outlines;
  S.open = new Set();
  S.bannerDismissed = false;
  S.morph = null;
  $("#btn-morph").classList.remove("on");
  if (!keepPick) S.pick = { ...data.start };
  S.shown = null;
  renderChips();
  renderFacts();
  renderDials();
  renderNearest();
  buildTicks();
  layoutStage();
  $("#scrubber").max = Math.max(0, S.frames.length - 1);
  $("#gen-of").textContent = `/ ${S.frames.length ? S.frames[S.frames.length - 1].gen : 0}`;
  if (!S.frames.length) renderWaiting();
  checkLiveStart();
}

/* Live run before its first generation: the start outline and an empty feed. */
function renderWaiting() {
  const r = S.run;
  S.shown = { outline: r.outlines[r.start_cid], params: r.start, cl: null, clLabel: "", ghostCid: null };
  $("#gen-num").textContent = "–";
  const st = $("#stage-status");
  st.className = "status";
  st.textContent = "STARTING";
  for (const id of ["#ro-cl", "#ro-cd", "#ro-solver", "#ro-stall"]) $(id).textContent = "—";
  updateDials(r.start);
  stageFoot();
  drawStage();
  drawPolar();
  hideBanner();
  $("#feed").innerHTML = `<div class="card"><div class="card-body"><p class="note">Waiting for generation 0: the Chief is planning and the start design is being solved.</p></div></div>`;
}

/* ------------------------------------------------------------------ header + facts */
function renderChips() {
  const r = S.run;
  const lab = $("#label-chip");
  lab.textContent = r.label;
  lab.classList.toggle("mock", !!r.is_mock);
  lab.title = r.mock_notice || r.llm_client || "";
}

function renderFacts() {
  const r = S.run, s = r.spec;
  $("#spec").innerHTML = [
    ["Target Cl", `${clTxt(s.target_cl)} ± ${s.cl_tol}`],
    ["Cd max", s.cd_max],
    ["Reynolds", s.reynolds.toExponential(1).replace("e+", "e")],
    ["Section", s.component === "wing_1el" ? "single element" : s.component],
    ["Rulebook", s.rulebook],
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
  $("#cad-box").innerHTML = cadLinks(r, true);
  $("#cad-box").hidden = !r.cad;

  const b = r.baseline, box = $("#baseline");
  if (!b) { box.hidden = true; return; }
  box.hidden = false;
  const swarm = r.outcome.result === "no_pass" ? "no pass" : `target met in ${r.outcome.evals_to_target} evals`;
  const opt = b.result === "no_pass"
    ? `no pass in ${b.evals} evals; closest Cl ${clTxt(b.cl)}, Cd ${fmt(b.cd, 4)} (${SOLVER[b.solver] || b.solver})`
    : `target met in ${b.evals_to_target} evals (Cl ${clTxt(b.cl)}, Cd ${fmt(b.cd, 4)})`;
  box.innerHTML = `<div class="t">vs Optuna TPE, same start</div>
    <div><b>Swarm:</b> ${esc(swarm)}</div>
    <div><b>Optuna:</b> ${esc(opt)}</div>
    ${b.failing && b.failing.length ? `<div class="why">closest fails: ${esc(b.failing[0])}</div>` : ""}
    <div class="why">Same spec, gates and budget, no LLM; sampler seed ${esc(b.seed)}. Run with the current pipeline code.</div>`;
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
    : [["var(--accent)", "current candidate", ""], ["var(--ghost)", "parent (base for this step)", "5 4"]];
  $("#stage-foot").innerHTML =
    items.map(([c, t, d]) => `<span><i class="sw" style="border-color:${c};${d ? "border-top-style:dashed" : ""}"></i>${t}</span>`).join("") +
    `<span>arrow: downforce ∝ |Cl| · race-car orientation (inverted, α applied)</span>`;
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
  const g = S.frames[S.fi], ev = headOf(g);
  $("#gen-num").textContent = g.gen;
  $("#scrubber").value = S.fi;
  const st = statusOf(ev);
  const status = $("#stage-status");
  status.className = `status ${st.cls}`;
  status.innerHTML = `${ICON[st.cls] || ""}${esc(st.text)}`;
  status.title = (ev.failing || []).join("\n");
  $("#ro-cl").textContent = clTxt(ev.cl);
  $("#ro-cd").textContent = fmt(ev.cd, 5);
  $("#ro-solver").textContent = (SOLVER[ev.solver] || ev.solver) + (ev.solver_level != null ? ` L${ev.solver_level}` : "");
  const sm = ev.stall;
  $("#ro-stall").textContent = sm && sm.dcl_dalpha != null ? `${sm.dcl_dalpha.toFixed(3)}/° ${sm.source === "xfoil_probe" ? "XF" : "NF"}` : "—";
  $("#ro-stall").title = sm ? `d|Cl|/dα ${sm.dcl_dalpha} vs threshold ${sm.threshold} (${sm.source === "xfoil_probe" ? "XFoil α+1/α+2 probe" : "NeuralFoil screen"}); ${sm.ok ? "ok" : "fails"}` : "no stall-margin evidence for this record";
  $("#story").innerHTML = narrate(g);
  for (const t of document.querySelectorAll("#ticks i")) t.style.opacity = Number(t.dataset.fi) <= S.fi ? 1 : 0.28;
  if (!S.tween) updateDials(ev.params);
  stageFoot();
  drawStage();
  renderFeed();
  drawPolar();
  const last = S.fi === S.frames.length - 1;
  if (last && !S.bannerDismissed && !liveRunning()) showBanner(); else hideBanner();
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
    if (S.fi >= S.frames.length - 1) { S.bannerDismissed = false; goTo(0, { instant: true }); }
    S.nextAt = performance.now() + dur(BASE_DWELL_MS) * 0.6;
  }
}
function setSpeed(v) {
  S.speed = v;
  for (const b of document.querySelectorAll(".speed button")) b.classList.toggle("on", Number(b.dataset.speed) === v);
}

/* ------------------------------------------------------------------ banner + morph */
function finalRecord() {
  const o = S.run.outcome;
  for (const g of S.run.generations) for (const e of g.evals) if (e.cid === o.cid && e.solver === o.solver && e.cl === o.cl) return { g, e };
  return null;
}
function showBanner() {
  const r = S.run, o = r.outcome, b = $("#banner");
  const fr = finalRecord();
  const mockNote = r.is_mock ? `<div class="b"><b>Mock run:</b> ${esc(r.mock_notice || "rule-based stand-in, not an LLM")}</div>` : "";
  const invalid = r.llm_valid === false ? `<div class="b"><b>Invalid LLM run</b> (see meta.json llm_health).</div>` : "";
  if (o.result !== "no_pass") {
    b.className = "banner pass";
    b.innerHTML = `<button class="close" aria-label="Dismiss">×</button>
      <div class="h">${ICON.pass}Target met · generation ${o.generation}</div>
      <div class="b">${SOLVER[o.solver] || o.solver} PASS <code>${esc(o.cid)}</code>: Cl <code>${clTxt(o.cl)}</code> (target ${clTxt(r.spec.target_cl)} ± ${r.spec.cl_tol}), Cd <code>${fmt(o.cd, 5)}</code> ≤ ${r.spec.cd_max}, stall margin ${fr?.e.stall?.dcl_dalpha != null ? `<code>${fr.e.stall.dcl_dalpha.toFixed(3)}/°</code>` : "ok"}.</div>
      <div class="b">${o.evals_to_target} evaluations${r.cost_usd != null ? ` · est. LLM cost $${r.cost_usd.toFixed(2)}` : ""} · termination <code>${esc(r.termination)}</code></div>${cadLinks(r)}${mockNote}${invalid}`;
  } else {
    b.className = "banner nopass";
    b.innerHTML = `<button class="close" aria-label="Dismiss">×</button>
      <div class="h">${ICON.miss}No passing design · ${esc(r.termination || "run ended")} after ${r.evals} evaluations</div>
      <div class="b">Closest candidate <code>${esc(o.cid || "—")}</code> (gen ${o.generation ?? "—"}, ${SOLVER[o.solver] || o.solver || "—"}): Cl <code>${clTxt(o.cl)}</code>, Cd <code>${fmt(o.cd, 5)}</code>. It fails:</div>
      <ul>${(o.failing || []).map((f) => `<li>${esc(f)}</li>`).join("")}</ul>${cadLinks(r)}${mockNote}${invalid}`;
  }
  const was = b.hidden;
  b.hidden = false;
  b.querySelector(".close").onclick = () => { S.bannerDismissed = true; hideBanner(); };
  if (was) layoutStage();
}
/* Download links for the run's CAD files (FreeCAD document, STEP, coordinates), built by the exporter. */
function cadLinks(r, panel = false) {
  const c = r.cad;
  if (!c) return "";
  if (c.error) return `<div class="b cad-files"><b>CAD files:</b> not built (${esc(c.error)})</div>`;
  const href = (f) => `${S.dataBase}runs/${c.dir}/${encodeURIComponent(f)}`;
  const kinds = [["fcstd", "FreeCAD model"], ["step", "STEP"], ["dat", "Coordinates (.dat)"]];
  const links = kinds.filter(([k]) => c.files[k]).map(([k, t]) => `<a href="${href(c.files[k])}" download>${t}</a>`).join("");
  const what = c.final_label && c.final_label.startsWith("closest") ? "closest candidate" : "optimized design";
  return `<div class="${panel ? "" : "b "}cad-files"><b>CAD files</b> (start and ${what}, ${c.chord_mm} mm chord, built in FreeCAD ${esc(c.check?.freecad_version || "")}):<span class="dl">${links}</span></div>`;
}

function hideBanner() {
  const b = $("#banner");
  if (b.hidden) return;
  b.hidden = true;
  layoutStage();
}

function toggleMorph() {
  if (S.morph) { stopMorph(); return; }
  const o = S.run.outcome;
  if (!o.cid) return;
  setPlaying(false);
  hideBanner();
  const startEv = headOf(S.frames[0]);
  const fr = finalRecord();
  S.morph = { startCid: startEv.cid, finalCid: o.cid, startEv, finalEv: fr?.e, t0: performance.now(), done: false };
  $("#btn-morph").classList.add("on");
  stageFoot();
  $("#gen-num").textContent = `0→${o.generation}`;
  const st = statusOf(fr?.e);
  $("#stage-status").className = `status ${st.cls}`;
  $("#stage-status").innerHTML = `${ICON[st.cls] || ""}START → ${o.result === "no_pass" ? "CLOSEST" : "FINAL"}`;
  $("#ro-cl").textContent = `${clTxt(startEv.cl)} → ${clTxt(o.cl)}`;
  $("#ro-cd").textContent = `${fmt(startEv.cd, 4)} → ${fmt(o.cd, 4)}`;
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

/* ------------------------------------------------------------------ feed */
function dirArrow(d) { return d === "+" ? "↑" : d === "-" ? "↓" : "↕"; }

function renderFeed() {
  const feed = $("#feed");
  const parts = [];
  for (let i = S.fi; i >= 0; i--) parts.push(card(S.frames[i], i === S.fi, i));
  feed.innerHTML = parts.join("");
  feed.scrollTop = 0;
  for (const h of feed.querySelectorAll(".card-head")) {
    h.addEventListener("click", () => {
      const g = Number(h.dataset.gen);
      const c = h.parentElement;
      c.classList.toggle("collapsed");
      if (c.classList.contains("collapsed")) S.open.delete(g); else S.open.add(g);
    });
  }
  for (const b of feed.querySelectorAll(".more")) {
    b.addEventListener("click", () => { b.previousElementSibling.querySelectorAll("[hidden]").forEach((n) => (n.hidden = false)); b.remove(); });
  }
}

function card(g, current, i) {
  const ev = headOf(g), st = statusOf(ev);
  const collapsed = !current && !S.open.has(g.gen);
  const parentP = S.cidParams[g.parent?.cid || ev?.parent_cid] || null;
  const out = [];
  const c = g.chief;
  if (c) {
    const tags = [c.mode === "inner_optimizer" ? "inner optimizer" : "reasoned step", SOLVER[c.fidelity] || c.fidelity, `trust ${c.trust_radius}`];
    out.push(`<div class="agent chief"><div class="who"><span data-tip="${esc(TIP.chief)}">Chief</span> <span class="tag">${esc(tags.join(" · "))}</span></div>
      <p class="quote">${esc(c.hypothesis)}</p>
      ${c.focus.length ? `<div class="focus">${c.focus.map((f) => `<span>${esc(SHORT[f.name] || f.name)} ${dirArrow(f.direction)}${f.locked ? " 🔒" : ""}</span>`).join("")}</div>` : ""}
      ${c.promote_cid ? `<div class="note">promote <code>${esc(c.promote_cid)}</code> to ${esc(SOLVER[c.fidelity] || c.fidelity)}</div>` : ""}
      ${c.declare_plateau ? `<div class="note">declares a plateau</div>` : ""}
      ${c.screen_override ? `<div class="override"><b>Screen override:</b> ${esc(c.screen_override)}</div>` : ""}</div>`);
  }
  if (g.parent && i > 0) out.push(`<div class="agent sys"><div class="who"><span data-tip="${esc(TIP.parent)}">Parent</span> <span class="tag">${esc(g.parent.cid)}</span></div><div class="note">${esc(g.parent.why)}</div></div>`);
  g.cad.forEach((a, k) => {
    const rejected = a.outcome === "rejected";
    const head = g.cad.length > 1 ? `attempt ${k + 1}${rejected ? " · rejected" : a.outcome ? " · accepted" : ""}` : rejected ? "rejected" : "";
    const ch = a.changes.map((x) => {
      const old = parentP ? parentP[x.name] : null;
      const dis = (a.disagreements || []).find((d) => d.param === x.name);
      return `<div class="change"><div class="pv">${esc(SHORT[x.name] || x.name)} ${old != null ? `${pval(x.name, old)} <span class="arrow">→</span> ` : "→ "}${pval(x.name, x.new_value)} <span class="arrow">${esc(PARAM_META[x.name]?.unit || "")}</span></div>
        <div class="mech">${esc(x.mechanism)}</div>
        ${x.override_reason ? `<div class="override"><b>Overrides the Chief${dis ? ` (Chief ${dirArrow(dis.chief)}, CAD ${dirArrow(dis.cad)})` : ""}:</b> ${esc(x.override_reason)}</div>` : ""}</div>`;
    }).join("");
    out.push(`<div class="agent cad attempt ${rejected ? "rejected" : ""}"><div class="who"><span data-tip="${esc(TIP.cad)}">CAD</span> <span class="tag">${esc(head)}</span></div>${ch}
      ${a.rejection ? `<div class="rej">✕ ${esc(a.rejection)}</div>` : ""}</div>`);
  });
  const inner = g.notes.find((n) => n.event === "inner_optimizer_finished");
  if (inner) out.push(`<div class="agent sys"><div class="who">Inner optimizer <span class="tag">Optuna TPE · no LLM</span></div><div class="note">${esc(inner.evals)} evaluations; stopped: ${esc(inner.stopped)}${inner.promotable?.length ? `; promotable ${esc(inner.promotable.join(", "))}` : ""}</div></div>`);
  const solves = g.evals.map((e) => {
    const s = statusOf(e);
    return `<div class="solve">${esc(SOLVER[e.solver] || e.solver)}${e.inner_optimizer ? " (inner)" : ""} · Cl ${clTxt(e.cl)} · Cd ${fmt(e.cd, 5)} · ${esc(s.text)}</div>` +
      (e.failing.length && !e.inner_optimizer ? `<ul class="ev">${e.failing.slice(0, 3).map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : "");
  });
  const shownSolves = solves.length > 4 ? solves.slice(0, 4).join("") + `<div class="note">+ ${solves.length - 4} more evaluations</div>` : solves.join("");
  out.push(`<div class="agent sys"><div class="who"><span data-tip="${esc(TIP.solver)}">Solver</span> <span class="tag">${esc(ev.cid)}</span></div>${shownSolves}</div>`);
  const cr = g.critic;
  if (cr) {
    const evid = cr.evidence.map((x, j) => `<li ${j >= 3 ? "hidden" : ""}>${esc(x)}</li>`).join("");
    out.push(`<div class="agent critic"><div class="who"><span data-tip="${esc(TIP.critic)}">Critic</span> <span class="tag">${esc(cr.status)} · ${esc(cr.symptom)}${cr.confidence != null ? ` · conf ${cr.confidence}` : ""}${g.critic_source === "numeric" ? " · numeric verdict (no LLM text)" : ""}</span></div>
      <ul class="ev">${evid}</ul>${cr.evidence.length > 3 ? `<button class="more">${cr.evidence.length - 3} more</button>` : ""}</div>`);
  }
  const other = g.notes.filter((n) => !["inner_optimizer_finished", "geometry_rejected", "proposal_rejected"].includes(n.event));
  if (other.length || g.llm_failures.length) {
    out.push(`<div class="agent sys"><div class="who">Events</div>${other.map((n) => `<div class="note">${esc(n.event.replaceAll("_", " "))}${n.reason ? `: ${esc(n.reason)}` : ""}${n.error ? `: ${esc(n.error)}` : ""}${n.action ? `: ${esc(n.action)}` : ""}</div>`).join("")}
      ${g.llm_failures.map((f) => `<div class="note">LLM call failed (${esc(f.role)}): ${esc(f.error)}</div>`).join("")}</div>`);
  }
  return `<article class="card ${current ? "current fresh" : "past"} ${collapsed ? "collapsed" : ""}">
    <div class="card-head" data-gen="${g.gen}"><span class="g">GEN ${g.gen}</span><span class="status ${st.cls}" style="padding:1px 7px;font-size:11px">${ICON[st.cls] || ""}${esc(st.text)}</span>
    <span class="res">${clTxt(ev.cl)} / ${fmt(ev.cd, 4)}</span></div>
    <div class="card-body">${out.join("")}</div></article>`;
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
  const bl = el("text", { class: "box-label", x: bx1 - 6, y: by0 - 5, "text-anchor": "end" }, g);
  bl.textContent = "target box";

  // trail through the headline record of each generation so far
  const shown = S.frames.slice(0, S.fi + 1);
  const trail = shown.map((f) => headOf(f)).filter((e) => e.cl != null && e.cd != null);
  if (trail.length) el("path", { class: "trail", d: "M" + trail.map((e) => `${X(e.cd).toFixed(1)} ${Y(e.cl).toFixed(1)}`).join("L") }, g);

  // Optuna's best / closest design
  if (b) {
    const ox = X(b.cd), oy = Y(b.cl), d = 7;
    el("path", { class: "opt", d: `M${ox} ${oy - d}L${ox + d} ${oy}L${ox} ${oy + d}L${ox - d} ${oy}Z` }, g);
    const t = el("text", { class: "tick", x: ox + 10, y: oy + 4 }, g);
    t.textContent = "Optuna";
  }

  const pts = [];
  shown.forEach((f, k) => f.evals.forEach((e) => { if (e.cl != null && e.cd != null) pts.push({ e, g: f, cur: k === S.fi && e === headOf(f) }); }));
  const color = { pass: "var(--good)", miss: "var(--warning)", fail: "var(--critical)", "": "var(--ink-3)" };
  for (const p of pts) {
    const x = X(p.e.cd), y = Y(p.e.cl), st = statusOf(p.e);
    const attrs = { class: `pt ${p.e.inner_optimizer ? "inner" : ""}`, fill: color[st.cls] };
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
        <div class="r"><span>Cl</span><span>${clTxt(p.e.cl)}</span></div><div class="r"><span>Cd</span><span>${fmt(p.e.cd, 5)}</span></div>
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
  renderLegend(!!b);
}

function renderLegend(hasOpt) {
  const dot = (c) => `<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="${c}"/></svg>`;
  $("#polar-legend").innerHTML =
    `<span>${dot("var(--good)")}full pass</span><span>${dot("var(--warning)")}target miss</span><span>${dot("var(--critical)")}failure</span>
     <span><svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.5" fill="none" stroke="var(--ink-2)" stroke-width="1.5"/></svg>NeuralFoil</span>
     <span><svg viewBox="0 0 12 12"><rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="var(--ink-2)" stroke-width="1.5"/></svg>XFoil</span>` +
    (hasOpt ? `<span><svg viewBox="0 0 12 12"><path d="M6 1L11 6L6 11L1 6Z" fill="none" stroke="var(--ink-2)" stroke-width="1.5"/></svg>Optuna</span>` : "");
}

/* ------------------------------------------------------------------ timeline */
function buildTicks() {
  const box = $("#ticks");
  box.innerHTML = "";
  const n = S.frames.length;
  S.frames.forEach((g, i) => {
    const e = headOf(g), t = document.createElement("i");
    t.className = `${statusOf(e).cls} ${e.solver !== "neuralfoil" ? "xf" : ""}`;
    t.style.left = n > 1 ? `${(i / (n - 1)) * 100}%` : "0";
    t.dataset.fi = i;
    t.title = `gen ${g.gen}: ${statusOf(e).text} (${SOLVER[e.solver] || e.solver})`;
    box.appendChild(t);
  });
}

function wireControls() {
  $("#btn-play").onclick = () => setPlaying(!S.playing);
  $("#btn-prev").onclick = () => { setPlaying(false); goTo(S.fi - 1); };
  $("#btn-next").onclick = () => { setPlaying(false); goTo(S.fi + 1); };
  $("#btn-restart").onclick = () => { S.bannerDismissed = false; goTo(0, { instant: true }); setPlaying(true); };
  $("#btn-morph").onclick = toggleMorph;
  $("#scrubber").addEventListener("input", (e) => { setPlaying(false); goTo(Number(e.target.value), { instant: true }); });
  for (const b of document.querySelectorAll(".speed button")) b.onclick = () => setSpeed(Number(b.dataset.speed));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, select, .dial svg")) return;
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
  feed: "What each agent decided this generation, quoted from the run's trace log. Long text is shortened, never reworded.",
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
  let s = `${solver} Cl <b>${clTxt(ev.cl)}</b> and Cd <b>${fmt(ev.cd, 4)}</b>: `;
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
    const acc = g.cad.find((a) => a.outcome === "accepted") || g.cad[g.cad.length - 1];
    const parentP = S.cidParams[ev.parent_cid] || null;
    if (acc) {
      const ch = acc.changes.map((x) => {
        const old = parentP ? parentP[x.name] : null;
        const dir = old == null ? "set" : x.new_value > old ? "raised" : x.new_value < old ? "lowered" : "kept";
        return `${dir} ${PLAIN[x.name] || x.name}${old != null ? ` ${pval(x.name, old)} → ${pval(x.name, x.new_value)}${unitOf(x.name)}` : ""}`;
      });
      const rejected = g.cad.filter((a) => a.outcome === "rejected");
      const why = (a) => (/^duplicate/.test(a.rejection || "") ? "it repeated a design already tested"
        : /^(bounds|trust_region|direction|not_allowed|unknown_param|no_change)/.test(a.rejection || "") ? "it broke the Chief's limits"
        : "it broke a geometry or rulebook check");
      const rej = rejected.length ? ` (Code rejected ${rejected.length === 1 ? "its first proposal" : `${rejected.length} earlier proposals`}: ${[...new Set(rejected.map(why))].join("; ")}.)` : "";
      const dis = acc.disagreements || [];
      const ovr = dis.length ? ` It <b>overruled the Chief</b> on ${dis.map((d) => PLAIN[d.param] || d.param).join(", ")}; its reason is in the feed.` : "";
      out.push(`<b>Change.</b> The CAD agent ${ch.join(", ")}.${rej}${ovr}`);
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

/* "How to read this": shown on the first visit, reopened with the ? button. Filled from the run's own spec. */
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
  try { localStorage.setItem("aeroswarm-intro-seen", "1"); } catch (_) { /* optional */ }
  if (play && S.frames.length > 1) { if (S.fi >= S.frames.length - 1) goTo(0, { instant: true }); setPlaying(true); }
}
function wireIntro() {
  $("#help").onclick = () => { setPlaying(false); openIntro(); };
  $("#intro-go").onclick = () => closeIntro(true);
  $("#intro-close").onclick = () => closeIntro(false);
  $("#intro-live").onclick = () => { closeIntro(false); $("#live").scrollIntoView({ behavior: "smooth", block: "center" }); $("#live-go").focus(); };
  $("#intro").addEventListener("click", (e) => { if (e.target.id === "intro") closeIntro(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#intro").hidden) closeIntro(false); });
}
function introSeen() {
  try { return localStorage.getItem("aeroswarm-intro-seen") === "1"; } catch (_) { return false; }
}

/* ------------------------------------------------------------------ live mode (local server only) */
// The page offers live runs only when it is served by `python -m swarm.live` (api/health answers). The stream
// carries the same per-generation records as a recorded export; when the run ends it is saved to the gallery.
S.live = { startOk: null, available: false, health: null, runId: null, es: null, running: false, attached: false, gens: new Set() };
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
}

function attachLive(runId, { own = false } = {}) {
  detachLive();
  setPlaying(false);
  S.live.runId = runId;
  S.live.running = true;
  S.live.attached = true;
  S.live.gens = new Set();
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
    liveStatus(`${p.evals} evaluations · $${p.cost_usd.toFixed(2)} of $${(S.live.budget ?? 0).toFixed(2)} · ${p.llm_calls} LLM calls · ${mm}:${ss}`);
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
      liveStatus(`The run stopped with an error: ${JSON.parse(e.data).message}`);
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
  buildTicks();
  layoutStage();
  $("#scrubber").max = Math.max(0, S.frames.length - 1);
  $("#gen-of").textContent = `/ ${g.gen}`;
  if (following) goTo(S.frames.length - 1, { instant: S.frames.length === 1 });
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
