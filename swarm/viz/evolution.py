"""Wing evolution viewer: before / middle / after strip PNG and morph GIF (BLUEPRINT §5).

- The middle frame is chosen automatically: the first usable round whose
  verdict diagnosed TE separation, else the round with the largest drag.
- Separation shading uses solver data (XFoil Cf < 0 persisting to the TE),
  never guesswork. Laminar bubbles are not shaded as separation.
- Morphing interpolates parameters, not coordinates: every in-between frame
  is a valid airfoil, labelled as interpolated. Only recorded frames carry Cl/Cd.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import imageio.v3 as iio  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from swarm.cad.build import placed  # noqa: E402
from swarm.ledger import objective, usable  # noqa: E402
from swarm.state import DesignSpec, EvalRecord, WingParams  # noqa: E402

FILL, EDGE, GHOST, SEP, OK, BAD = "#5DCAA5", "#0F6E56", "0.6", "#E4572E", "#1B9E4B", "0.15"
XLIM, YLIM = (-0.1, 1.2), (-0.16, 0.36)


def pick_frames(ledger: list[EvalRecord], spec: DesignSpec) -> tuple[EvalRecord, EvalRecord, EvalRecord]:
    ok = [r for r in ledger if usable(r)]
    first, final = ok[0], min(ok, key=lambda r: objective(r.result, spec))
    diag = [
        r
        for r in ok
        if r.verdict and r.verdict.diagnosis.symptom in ("TE_SEPARATION_MAIN", "TE_SEPARATION_FLAP", "EARLY_STALL")
    ]
    if diag:
        return first, diag[0], final
    rest = [r for r in ok if r.params.cid not in (first.params.cid, final.params.cid)]
    if not rest:
        return first, final, final
    # the biggest drag jump relative to the previous usable round tells the story
    prev = {id(b): a for a, b in zip(ok, ok[1:], strict=False)}
    middle = max(rest, key=lambda r: r.result.cd - (prev[id(r)].result.cd if id(r) in prev else r.result.cd))
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


def _readout(ax, rec: EvalRecord | None, spec: DesignSpec) -> None:
    if rec is None:
        return
    r = rec.result
    cl_ok = abs(r.cl - spec.target_cl) <= spec.cl_tol
    cd_ok = r.cd <= spec.cd_max
    ax.text(
        0.98,
        0.95,
        f"Cl {r.cl:+.3f}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color=OK if cl_ok else BAD,
        fontsize=10,
        family="monospace",
        weight="bold",
    )
    ax.text(
        0.98,
        0.83,
        f"Cd {r.cd:.4f}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color=OK if cd_ok else BAD,
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


def draw(ax, p: WingParams, ghost: WingParams, rec: EvalRecord | None, spec: DesignSpec, label: str) -> None:
    g = placed(ghost)
    ax.plot(*np.vstack([g, g[:1]]).T, "--", color=GHOST, lw=1)
    w = placed(p)
    ax.fill(*w.T, color=FILL, ec=EDGE, lw=1.2)
    bl = rec.result.bl if rec else None
    if bl and bl.te_separation_xc is not None:
        poly = _sep_polygon(p, bl.te_separation_xc)
        ax.fill(*poly.T, color=SEP, alpha=0.35, lw=0)
        ax.text(
            0.02,
            0.06,
            f"TE separation from x/c {bl.te_separation_xc:.2f}",
            transform=ax.transAxes,
            color=SEP,
            fontsize=8,
        )
    ax.set(xlim=XLIM, ylim=YLIM, aspect="equal")
    ax.axis("off")
    ax.text(0.02, 0.95, label, transform=ax.transAxes, fontsize=10, va="top")
    _readout(ax, rec, spec)


def _render(fig) -> np.ndarray:
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img


def strip_png(ledger: list[EvalRecord], spec: DesignSpec, path: Path) -> Path:
    first, middle, final = pick_frames(ledger, spec)
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.4), dpi=110)
    for ax, rec, title in zip(axes, (first, middle, final), ("before", "middle", "after"), strict=True):
        draw(ax, rec.params, first.params, rec, spec, f"{title}: round {rec.generation} · {rec.params.cid}")
    fig.suptitle(
        f"Target Cl {spec.target_cl} ± {spec.cl_tol}, Cd ≤ {spec.cd_max}, "
        f"Re {spec.reynolds:.2e}  (inverted section, race-car orientation; dashed = start)",
        fontsize=10,
    )
    fig.tight_layout()
    iio.imwrite(path, _render(fig))
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


def write_evolution(ledger: list[EvalRecord], spec: DesignSpec, out_dir: str | Path) -> dict[str, str]:
    out = Path(out_dir)
    return {
        "strip": str(strip_png(ledger, spec, out / "evolution_strip.png")),
        "gif": str(morph_gif(ledger, spec, out / "evolution_morph.gif")),
    }
