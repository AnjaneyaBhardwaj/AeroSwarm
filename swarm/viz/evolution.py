"""Wing evolution viewer: before / middle / after strip PNG, morph GIF and stall-margin plots (BLUEPRINT §5).

- "after" is the best passing design (a full PASS: XFoil, in the box, attached, with a
  stall margin). If nothing passed it is the closest candidate, labelled "no passing
  design — closest candidate" with its failing check. A TARGET_MISS is never called best.
- "middle" is the most instructive failure, never the same cid as "after": the worst
  measured stall margin, else the first TE separation, else the worst NeuralFoil screen,
  else the largest drag jump.
- Every recorded frame shows its verdict status; green is used only for a full PASS.
- Separation shading uses solver data (XFoil Cf < 0 persisting to the TE),
  never guesswork. Laminar bubbles are not shaded as separation.
- Morphing interpolates parameters, not coordinates: every in-between frame
  is a valid airfoil, labelled as interpolated. Only recorded frames carry Cl/Cd.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import imageio.v3 as iio  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from swarm.cad.build import placed  # noqa: E402
from swarm.ledger import best_passing, closest_candidate, failing_checks, objective, passing, usable  # noqa: E402
from swarm.state import DesignSpec, EvalRecord, WingParams  # noqa: E402

FILL, EDGE, GHOST, SEP, OK, BAD = "#5DCAA5", "#0F6E56", "0.6", "#E4572E", "#1B9E4B", "0.15"
XLIM, YLIM = (-0.1, 1.2), (-0.16, 0.36)


def _instructive_failure(pool: list[EvalRecord], first: EvalRecord) -> EvalRecord | None:
    stalled = [r for r in pool if r.stall_margin is not None and not r.stall_margin.ok]
    measured = [r for r in stalled if r.stall_margin.dcl_dalpha is not None]
    if measured:
        return min(measured, key=lambda r: r.stall_margin.dcl_dalpha)
    if stalled:  # a probe that could not be solved
        return stalled[0]
    sep = [
        r
        for r in pool
        if (r.result.bl is not None and r.result.bl.te_separation_xc is not None)
        or (r.verdict and r.verdict.diagnosis.symptom in ("TE_SEPARATION_MAIN", "TE_SEPARATION_FLAP", "EARLY_STALL"))
    ]
    if sep:
        return sep[0]
    screened = [r for r in pool if r.screen is not None and not r.screen.ok and r.screen.dcl_dalpha is not None]
    if screened:
        return min(screened, key=lambda r: r.screen.dcl_dalpha)
    rest = [r for r in pool if r.params.cid != first.params.cid]
    if not rest:
        return None
    # the biggest drag jump relative to the previous usable round tells the story
    ok = [first] + rest
    prev = {id(b): a for a, b in zip(ok, ok[1:], strict=False)}
    return max(rest, key=lambda r: r.result.cd - (prev[id(r)].result.cd if id(r) in prev else r.result.cd))


def pick_frames(ledger: list[EvalRecord], spec: DesignSpec) -> tuple[EvalRecord, EvalRecord, EvalRecord]:
    """(before, middle, after). `after` is the best passing design, else the closest candidate
    (check with `ledger.passing`); `middle` never has the same cid as `after`, and is the start
    design only when nothing else failed."""
    ok = [r for r in ledger if usable(r)]
    first = ok[0]
    final = best_passing(ledger, spec) or closest_candidate(ledger, spec) or first
    pool = [r for r in ok if r.params.cid != final.params.cid]
    later = [r for r in pool if r.params.cid != first.params.cid]
    middle = _instructive_failure(later, first) or _instructive_failure(pool, first)
    if middle is None:  # every usable round is the final design: nothing else to show
        middle = first
    return first, middle, final


def blend(pa: WingParams, pb: WingParams, f: float) -> WingParams:
    return WingParams(**{k: (1 - f) * getattr(pa, k) + f * getattr(pb, k) for k in WingParams.model_fields})


def _sep_polygon(p: WingParams, sep_xc: float) -> np.ndarray:
    """Region from the separation point on the suction surface to the TE, into the wake."""
    xy = placed(p)
    n = (len(xy) + 1) // 2
    # Inverted section: the upright upper (suction) surface is now the lower side.
    suction = xy[:n][::-1]  # LE → TE
    lead = np.argmin(xy[:, 0])
    chord_x = xy[:, 0] - xy[lead, 0]
    span = chord_x.max()
    s_idx = np.where(chord_x[:n][::-1] >= sep_xc * span)[0]
    pts = suction[s_idx]
    te = pts[-1]
    a = np.deg2rad(p.alpha_deg)
    wake_dir = np.array([np.cos(a), np.sin(a)])
    thick = 0.04 + 0.25 * (1 - sep_xc) * 0.3
    wake_end = te + 0.12 * wake_dir
    normal = np.array([np.sin(a), -np.cos(a)])
    return np.vstack([pts, wake_end, wake_end + thick * normal, pts[0] + 0.01 * normal])


def _status(rec: EvalRecord, spec: DesignSpec) -> tuple[str, str, list[str]]:
    """(status text, colour, failing checks). Green only for a full PASS."""
    if passing(rec):
        return "PASS", OK, []
    status = rec.verdict.status if rec.verdict else rec.result.status
    if status == "PASS":  # a lower-tier PASS is not a pass
        status = f"PASS at {rec.result.fidelity} only (not a full PASS)"
    return status, SEP, failing_checks(rec, spec)


def _readout(ax, rec: EvalRecord | None, spec: DesignSpec, show_checks: bool = False) -> None:
    if rec is None:
        return
    r = rec.result
    colour = OK if passing(rec) else BAD
    for y, text in ((0.95, f"Cl {r.cl:+.3f}"), (0.83, f"Cd {r.cd:.4f}")):
        ax.text(
            0.98,
            y,
            text,
            transform=ax.transAxes,
            ha="right",
            va="top",
            color=colour,
            fontsize=10,
            family="monospace",
            weight="bold",
        )
    ax.text(
        0.98,
        0.71,
        f"{r.fidelity}{' (fallback)' if r.lower_fidelity else ''}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color="0.4",
        fontsize=8,
        family="monospace",
    )
    status, scolour, why = _status(rec, spec)
    ax.text(0.02, 0.97, status, transform=ax.transAxes, va="top", color=scolour, fontsize=9, weight="bold")
    if show_checks and why:
        ax.text(
            0.02,
            0.86,
            "\n".join(textwrap.fill(w, 62) for w in why[:2]),
            transform=ax.transAxes,
            va="top",
            color=SEP,
            fontsize=7.5,
        )


def draw(
    ax,
    p: WingParams,
    ghost: WingParams,
    rec: EvalRecord | None,
    spec: DesignSpec,
    label: str,
    show_checks: bool = False,
) -> None:
    g = placed(ghost)
    ax.plot(*np.vstack([g, g[:1]]).T, "--", color=GHOST, lw=1)
    w = placed(p)
    ax.fill(*w.T, color=FILL, ec=EDGE, lw=1.2)
    bl = rec.result.bl if rec else None
    if bl and bl.te_separation_xc is not None:
        poly = _sep_polygon(p, bl.te_separation_xc)
        ax.fill(*poly.T, color=SEP, alpha=0.35, lw=0)
        ax.text(
            0.98,
            0.59,
            f"TE separation from x/c {bl.te_separation_xc:.2f}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            color=SEP,
            fontsize=8,
        )
    ax.set(xlim=XLIM, ylim=YLIM, aspect="equal")
    ax.axis("off")
    ax.set_title(label, fontsize=9.5, loc="left")
    _readout(ax, rec, spec, show_checks)


def _render(fig) -> np.ndarray:
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img


def strip_png(ledger: list[EvalRecord], spec: DesignSpec, path: Path) -> Path:
    first, middle, final = pick_frames(ledger, spec)
    after = "after: best passing design" if passing(final) else "no passing design — closest candidate"
    titles = ("before", "most instructive failure", after)
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.8), dpi=110)
    for ax, rec, title in zip(axes, (first, middle, final), titles, strict=True):
        label = f"{title}: round {rec.generation} · {rec.params.cid}"
        draw(ax, rec.params, first.params, rec, spec, label, show_checks=rec is not first)
    fig.suptitle(
        f"Target Cl {spec.target_cl} ± {spec.cl_tol}, Cd ≤ {spec.cd_max}, "
        f"Re {spec.reynolds:.2e}  (inverted section, race-car orientation; dashed = start; green = full PASS only)",
        fontsize=10,
    )
    fig.tight_layout()
    iio.imwrite(path, _render(fig))
    return path


def stall_plot(rec: EvalRecord, spec: DesignSpec, path: Path) -> Path:
    """Downforce |Cl| at alpha, +1, +2 deg from the XFoil stall-margin probe, each secant
    against the d|Cl|/dalpha threshold; the NeuralFoil screen of the same geometry for reference."""
    sm = rec.stall_margin
    assert sm is not None
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=110)
    lo, hi = abs(spec.target_cl) - spec.cl_tol, abs(spec.target_cl) + spec.cl_tol
    ax.axhspan(lo, hi, color=OK, alpha=0.08, lw=0, label=f"target |Cl| {abs(spec.target_cl)} ± {spec.cl_tol}")
    pts = [(a, abs(c)) for a, c in zip(sm.alphas_deg, sm.cls, strict=True) if c is not None]
    for (a0, c0), (a1, c1) in zip(pts, pts[1:], strict=False):
        slope = (c1 - c0) / (a1 - a0)
        good = slope >= sm.threshold
        ax.plot([a0, a1], [c0, c1], "-", color=OK if good else SEP, lw=2)
        ax.plot([a0, a1], [c0, c0 + sm.threshold * (a1 - a0)], "--", color="0.45", lw=1)
        # The threshold line runs above a failing segment and below a passing one: label the other side.
        ax.annotate(
            f"{slope:+.3f}/deg",
            ((a0 + a1) / 2, (c0 + c1) / 2),
            textcoords="offset points",
            xytext=(6, 10) if good else (6, -12),
            ha="left" if not good else "right",
            va="bottom" if good else "top",
            fontsize=8,
            color=OK if good else SEP,
            bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.85},
        )
    ax.plot([], [], "--", color="0.45", lw=1, label=f"threshold slope {sm.threshold}/deg")
    ax.plot(*zip(*pts, strict=True), "o", color=EDGE, ms=6, label="XFoil (probe)")
    for a, c, x in zip(sm.alphas_deg, sm.cls, sm.te_separation_xc or [None] * len(sm.cls), strict=False):
        if c is not None and x is not None:
            ax.annotate(
                f"TE sep x/c {x:.2f}", (a, abs(c)), textcoords="offset points", xytext=(4, -12), fontsize=7, color=SEP
            )
    if rec.screen is not None:
        sc = rec.screen
        ax.plot(
            sc.alphas_deg,
            [abs(c) for c in sc.cls],
            "o:",
            mfc="none",
            color="0.5",
            ms=6,
            label=f"NeuralFoil screen (min {sc.dcl_dalpha:+.3f}/deg)",
        )
    margin = "probe failed" if sm.dcl_dalpha is None else f"{sm.dcl_dalpha:+.3f}/deg"
    verdict = "ok" if sm.ok else "FAIL"
    ax.set(
        xlabel="alpha (deg)",
        ylabel="downforce |Cl|",
        title=f"{rec.params.cid} (round {rec.generation}): stall margin {margin} vs {sm.threshold} → {verdict}",
    )
    ax.title.set_fontsize(9)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def morph_gif(ledger: list[EvalRecord], spec: DesignSpec, path: Path, steps: int = 8, max_keyframes: int = 12) -> Path:
    ok = [r for r in ledger if usable(r)]
    # keyframes: the best-so-far trajectory (each improvement), capped in length
    keys, best = [], float("inf")
    for r in ok:
        j = objective(r.result, spec)
        if j < best - 1e-9:
            keys.append(r)
            best = j
    if len(keys) > max_keyframes:
        idx = np.linspace(0, len(keys) - 1, max_keyframes).round().astype(int)
        keys = [keys[i] for i in sorted(set(idx))]
    frames = []
    ghost = keys[0].params

    def frame(p, rec, label):
        fig, ax = plt.subplots(figsize=(8, 3), dpi=90)
        draw(ax, p, ghost, rec, spec, label)
        fig.tight_layout()
        return _render(fig)

    for a, b in zip(keys, keys[1:], strict=False):
        frames += [frame(a.params, a, f"round {a.generation} (recorded)")] * 3
        for f in np.linspace(0, 1, steps, endpoint=False)[1:]:
            frames.append(
                frame(blend(a.params, b.params, f), None, f"round {a.generation} → {b.generation} (interpolated)")
            )
    last = keys[-1]
    frames += [frame(last.params, last, f"final: round {last.generation} (recorded)")] * 10
    iio.imwrite(path, np.stack(frames), duration=80, loop=0)
    return path


def write_evolution(ledger: list[EvalRecord], spec: DesignSpec, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    stall = {}
    for rec in ledger:
        if rec.stall_margin is not None and rec.params.cid not in stall:
            stall[rec.params.cid] = str(stall_plot(rec, spec, out / f"stall_{rec.params.cid}.png"))
    return {
        "strip": str(strip_png(ledger, spec, out / "evolution_strip.png")),
        "gif": str(morph_gif(ledger, spec, out / "evolution_morph.gif")),
        "stall_plots": stall,
    }
