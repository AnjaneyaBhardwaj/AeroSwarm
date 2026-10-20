/* Home page flipbook: every try of the example run, one at a time.
 * Outlines and numbers come only from the run's export (runs/example_hard_llm.json), like the replay.
 * Until it loads (or if it can't), the static start-and-final picture stays. */
(function () {
  "use strict";
  const root = document.getElementById("flip");
  if (!root || !window.fetch) return;

  const $ = (id) => document.getElementById(id);
  const SVGNS = "http://www.w3.org/2000/svg";
  const WHO = { neuralfoil: "measured by the Hare (NeuralFoil)", xfoil: "measured by the Tortoise (XFoil)" };
  const STEP_MS = 420;
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const minus = (x, dp) => (x < 0 ? "−" : "") + Math.abs(x).toFixed(dp);
  const num = (x) => (x < 0 ? "−" : "") + Math.abs(x); // spec values as written: −1.83, not −1.8300
  const listJoin = (xs) => (xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1]);
  const pathOf = (ol) => "M" + ol.map(([x, y]) => x.toFixed(3) + " " + y.toFixed(3)).join("L") + "Z";

  let run, tries, scales, cur, timer = null;

  fetch("runs/example_hard_llm.json")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
    .then(build)
    .catch(() => {}); // keep the static picture

  function build(r) {
    run = r;
    tries = r.generations.flatMap((g) => g.evals.map((e) => ({ gen: g.gen, e }))).filter((t) => r.outlines[t.e.cid]);
    if (!tries.length || !r.outlines[r.start_cid]) return;

    // the wing: this try filled, the start dashed on top (same drawing as the static picture)
    const svg = $("flip-svg");
    svg.textContent = "";
    const shape = (cls, d) => {
      const p = document.createElementNS(SVGNS, "path");
      p.setAttribute("class", cls);
      p.setAttribute("vector-effect", "non-scaling-stroke");
      p.setAttribute("transform", "translate(20 58) scale(260 -260)");
      p.setAttribute("d", d);
      return svg.appendChild(p);
    };
    shape("ba-final flip-cur", pathOf(r.outlines[tries[0].e.cid]));
    shape("ba-start", pathOf(r.outlines[r.start_cid]));

    const s = r.spec;
    const cls = tries.map((t) => Math.abs(t.e.cl)).concat([Math.abs(s.target_cl) - s.cl_tol, Math.abs(s.target_cl) + s.cl_tol]);
    const cds = tries.map((t) => t.e.cd).concat([s.cd_max]);
    const pad = (lo, hi) => [lo - (hi - lo) * 0.08, hi + (hi - lo) * 0.08];
    const push = pad(Math.min(...cls), Math.max(...cls)), drag = pad(Math.min(...cds), Math.max(...cds));
    const pct = (v, [lo, hi]) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100)).toFixed(2) + "%";
    $("flip-meters").innerHTML =
      meter("push", "Push", pct(Math.abs(s.target_cl) - s.cl_tol, push), pct(Math.abs(s.target_cl) + s.cl_tol, push),
        `target ${num(s.target_cl)} ± ${s.cl_tol}`) +
      meter("drag", "Drag", pct(drag[0], drag), pct(s.cd_max, drag), `limit ${s.cd_max}`);
    scales = { push, drag, pct };

    const range = $("flip-range");
    range.max = String(tries.length);
    range.addEventListener("input", () => { stop(); show(+range.value - 1); });
    $("flip-play").addEventListener("click", () => (timer ? stop() : play()));
    $("flip-panel").hidden = false;
    root.classList.add("live");
    show(tries.length - 1);

    // Play it through once when it first comes into view (not for reduced motion).
    if (!reduced() && "IntersectionObserver" in window) {
      const io = new IntersectionObserver((seen) => {
        if (seen.some((x) => x.isIntersecting)) { io.disconnect(); play(); }
      }, { threshold: 0.6 });
      io.observe($("flip-svg"));
    }
  }

  function meter(id, label, z0, z1, foot) {
    return `<div class="meter ${id}"><div class="m-top"><span class="m-k">${label}</span><span class="m-v num" id="m-${id}"></span></div>
      <div class="m-track"><span class="m-zone" style="left:${z0};width:calc(${z1} - ${z0})"></span><span class="m-mark" id="m-${id}-mark"></span></div>
      <div class="m-foot">${foot}</div></div>`;
  }

  function verdict(e) {
    const s = run.spec;
    if (e.passing) return ["pass", "Passed. The Tortoise made it official: target met."];
    if (e.verdict === "PASS") return ["screen", "The Hare's quick check says it passes. Only the Tortoise can make it official."];
    const why = [], off = Math.abs(e.cl) - Math.abs(s.target_cl);
    if (Math.abs(e.cl - s.target_cl) > s.cl_tol) why.push(off < 0 ? `${(-off).toFixed(3)} short on push` : `${off.toFixed(3)} too much push`);
    if (e.cd > s.cd_max) why.push("too much drag");
    if (e.stall && e.stall.ok === false) why.push("close to stalling");
    return ["miss", why.length ? `Not yet: ${listJoin(why)}.` : `Not yet: ${e.failing[0] || "it failed a check"}.`];
  }

  function show(i) {
    cur = i;
    const { gen, e } = tries[i], s = run.spec, sc = scales;
    const d = pathOf(run.outlines[e.cid]);
    const p = root.querySelector(".flip-cur");
    p.setAttribute("d", d);
    p.style.d = `path("${d}")`; // lets browsers that can, glide between shapes
    $("flip-range").value = String(i + 1);
    $("flip-try").textContent = `Try ${i + 1} of ${tries.length}`;
    $("flip-who").textContent = `round ${gen}, ${WHO[e.solver] || e.solver}`;
    $("flip-which").textContent = i === tries.length - 1 ? "final" : `try ${i + 1}'s`;
    const inCl = Math.abs(e.cl - s.target_cl) <= s.cl_tol, inCd = e.cd <= s.cd_max;
    $("m-push").textContent = `Cl ${minus(e.cl, 4)}`;
    $("m-drag").textContent = `Cd ${e.cd.toFixed(4)}`;
    for (const [id, v, ok, scale] of [["push", Math.abs(e.cl), inCl, sc.push], ["drag", e.cd, inCd, sc.drag]]) {
      const m = $(`m-${id}-mark`);
      m.style.left = sc.pct(v, scale);
      m.classList.toggle("ok", ok);
    }
    const [kind, text] = verdict(e);
    const v = $("flip-verdict");
    v.className = `flip-verdict ${kind}`;
    v.textContent = text;
  }

  function play() {
    if (cur >= tries.length - 1) show(0);
    setIcon(true);
    timer = setInterval(() => {
      if (cur >= tries.length - 1) return stop();
      show(cur + 1);
    }, reduced() ? STEP_MS * 2 : STEP_MS);
  }
  function stop() {
    clearInterval(timer);
    timer = null;
    setIcon(false);
  }
  function setIcon(playing) {
    $("flip-play-icon").setAttribute("d", playing ? "M7 5h4v14H7zM13 5h4v14h-4z" : "M7 5v14l12-7z");
    $("flip-play").setAttribute("aria-label", playing ? "Pause" : "Play through every try");
  }
})();
