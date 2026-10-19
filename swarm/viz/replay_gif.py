"""Replay GIF for the README: the wing morphing beside the Cl–Cd polar as it fills in (BLUEPRINT §5 hero asset).

The input is a viewer export (`viewer/runs/<name>.json`, written by `swarm/viz/export.py`), so every number on a
frame comes from the run ledger and every recorded shape is the exporter's own outline. Colours follow the
viewer's tokens (`viewer/style.css`), in a light and a dark variant for the README's `<picture>`.

- One recorded frame per generation that has a headline record, held. Its header shows that record's
  generation, status, Cl, Cd and solver; the polar shows every evaluation up to that generation.
- Between two recorded frames the section morphs by interpolating the parameters (`WingParams`) and rebuilding
  the outline with the exporter's `outline`, so every in-between shape is a valid section. In-between frames are
  labelled "interpolated" and carry no new numbers: header, polar and downforce arrow stay on the last recorded
  generation until the next one is reached.
- The last recorded frame is held longest, with the run's result from the export's `outcome`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager, ticker  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Polygon, Rectangle  # noqa: E402
from matplotlib.text import Annotation  # noqa: E402
from PIL import Image  # noqa: E402

from swarm.state import WingParams  # noqa: E402
from swarm.viz.export import outline  # noqa: E402

SOLVER = {"neuralfoil": "NeuralFoil", "xfoil": "XFoil", "of2d": "OpenFOAM 2D", "of3d": "OpenFOAM 3D"}
ARROW_K = 0.13  # downforce arrow length per unit |Cl|, in chords (as in the viewer)
SIZE_IN = (9.6, 4.1)  # 960 x 410 px at dpi 100

# viewer/style.css tokens
THEMES = {
    "light": {
        "bg": "#fcfcfb",
        "line": "#dcdfe3",
        "line2": "#c6cad0",
        "ink": "#0f1419",
        "ink2": "#4a5360",
        "ink3": "#7b8491",
        "accent": "#0f8f84",
        "ghost": "#9aa3ad",
        "good": "#0ca30c",
        "good_ink": "#067a06",
        "warning": "#fab219",
        "warning_ink": "#8a5d00",
        "critical": "#d03b3b",
        "critical_ink": "#b02a2a",
        "target_alpha": 0.10,
    },
    "dark": {
        "bg": "#14181d",
        "line": "#262c34",
        "line2": "#343c46",
        "ink": "#e9edf1",
        "ink2": "#a9b2bd",
        "ink3": "#6f7a87",
        "accent": "#36c2b4",
        "ghost": "#56606c",
        "good": "#0ca30c",
        "good_ink": "#3fd13f",
        "warning": "#fab219",
        "warning_ink": "#fab219",
        "critical": "#d03b3b",
        "critical_ink": "#ff7a7a",
        "target_alpha": 0.13,
    },
}
KIND_COLOUR = {"pass": "good", "miss": "warning", "fail": "critical"}
KIND_INK = {"pass": "good_ink", "miss": "warning_ink", "fail": "critical_ink"}


# ------------------------------------------------------------------ data (no drawing)
def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def recorded(export: dict) -> list[dict]:
    """The generations that have a headline record, in order: one recorded frame each."""
    return [g for g in export["generations"] if g["head"] >= 0]


def head(g: dict) -> dict:
    return g["evals"][g["head"]]


def status_of(ev: dict) -> tuple[str, str]:
    """(label, kind) as the viewer shows it; kind is pass / miss / fail. PASS only for a full pass."""
    if ev.get("passing"):
        return "PASS", "pass"
    v = ev.get("verdict") or ev.get("solver_status")
    if v == "PASS":  # a lower-fidelity PASS is not a pass
        return f"PASS at {SOLVER.get(ev['solver'], ev['solver'])} only", "miss"
    if v == "TARGET_MISS":
        return "TARGET MISS", "miss"
    return str(v or "FAILED").replace("_", " "), "fail"


def cl_txt(x: float | None) -> str:
    return "—" if x is None else ("−" if x < 0 else "") + f"{abs(x):.4f}"


def spec_num(x: float) -> str:
    """A spec value as written (−1.83, not −1.8300)."""
    return ("−" if x < 0 else "") + f"{abs(x):g}"


@dataclass(frozen=True)
class Frame:
    i: int  # recorded frame shown (index into recorded())
    f: float = 0.0  # 0: the recorded frame itself; 0 < f < 1: shape on its way to recorded frame i + 1
    ms: int = 0
    final: bool = False


def plan(
    export: dict,
    hold_ms: int = 340,
    tween: int = 3,
    tween_ms: int = 50,
    first_ms: int = 900,
    final_ms: int = 3000,
) -> list[Frame]:
    """Frame sequence and durations. A morph is skipped (its time added to the hold) when two consecutive
    recorded frames show the same design, e.g. an XFoil check of the design just shown."""
    rec = recorded(export)
    if not rec:
        raise ValueError("the export has no generation with a recorded result")
    out: list[Frame] = []
    for i, g in enumerate(rec):
        if i == len(rec) - 1:
            out.append(Frame(i, 0.0, final_ms, final=True))
            break
        same = head(g)["cid"] == head(rec[i + 1])["cid"]
        hold = first_ms if i == 0 else hold_ms
        out.append(Frame(i, 0.0, hold + (tween * tween_ms if same else 0)))
        if not same:
            out += [Frame(i, k / (tween + 1), tween_ms) for k in range(1, tween + 1)]
    return out


def result_line(export: dict) -> tuple[str, str]:
    """(text, kind) for the last frame, from the export's outcome."""
    o = export["outcome"]
    if o["result"] != "no_pass":
        solver = SOLVER.get(o["solver"], o["solver"])
        return (
            f"Target met in {o['evals_to_target']} evaluations: Cl {cl_txt(o['cl'])}, Cd {o['cd']:.4f}, "
            f"confirmed by {solver}",
            "pass",
        )
    return f"No passing design in {export['evals']} evaluations", "miss"


def facts(export: dict, fr: Frame) -> dict:
    """Everything a frame says in words and numbers. Numbers are the recorded frame's headline record."""
    rec = recorded(export)
    g = rec[fr.i]
    ev = head(g)
    s = export["spec"]
    label, kind = status_of(ev)
    interpolated = 0 < fr.f < 1
    if fr.final:
        footer, footer_kind = result_line(export)
    else:
        footer = f"Goal: Cl {spec_num(s['target_cl'])} ± {s['cl_tol']:g} and Cd ≤ {s['cd_max']:g}, confirmed by XFoil"
        footer_kind = None
    if export.get("is_mock"):
        footer += " (mock run, not an LLM)"
    return {
        "gen": g["gen"],
        "of": rec[-1]["gen"],
        "status": label,
        "kind": kind,
        "cl": cl_txt(ev["cl"]),
        "cd": "—" if ev["cd"] is None else f"{ev['cd']:.5f}",
        "solver": SOLVER.get(ev["solver"], ev["solver"]),
        "cl_ok": ev["cl"] is not None and abs(ev["cl"] - s["target_cl"]) <= s["cl_tol"],
        "cd_ok": ev["cd"] is not None and ev["cd"] <= s["cd_max"],
        "abs_cl": abs(ev["cl"] or 0.0),
        "interpolated": interpolated,
        "toward": rec[fr.i + 1]["gen"] if interpolated else None,
        "footer": footer,
        "footer_kind": footer_kind,
    }


def shape(export: dict, fr: Frame) -> np.ndarray:
    """The section drawn on a frame: the exporter's outline, or a parameter blend rebuilt the same way."""
    rec = recorded(export)
    a = head(rec[fr.i])
    if fr.f == 0:
        return np.asarray(export["outlines"][a["cid"]], dtype=float)
    b = head(rec[fr.i + 1])
    pa, pb = a["params"], b["params"]
    mix = {k: (1 - fr.f) * pa[k] + fr.f * pb[k] for k in pa}
    n = (len(export["outlines"][a["cid"]]) + 1) // 2
    return np.asarray(outline(WingParams(**mix), n=n), dtype=float)


# ------------------------------------------------------------------ drawing
@cache
def _family(*names: str) -> str:
    for name in names:
        try:
            font_manager.findfont(font_manager.FontProperties(family=name), fallback_to_default=False)
            return name
        except ValueError:
            continue
    return "DejaVu Sans"


def _fonts() -> tuple[str, str]:
    return _family("Inter", "DejaVu Sans"), _family("JetBrains Mono", "DejaVu Sans Mono")


def _bounds(export: dict) -> dict:
    """Fixed axes for the whole GIF, so nothing jumps between frames."""
    pts = np.vstack([np.asarray(o, dtype=float) for o in export["outlines"].values()])
    s = export["spec"]
    evals = [e for g in export["generations"] for e in g["evals"] if e["cl"] is not None and e["cd"] is not None]
    max_cl = max([abs(s["target_cl"])] + [abs(e["cl"]) for e in evals])
    wing = (
        pts[:, 0].min() - 0.2,
        pts[:, 0].max() + 0.06,
        pts[:, 1].min() - max_cl * ARROW_K - 0.08,
        pts[:, 1].max() + 0.06,
    )
    cds = [e["cd"] for e in evals] + [s["cd_max"]]
    cls = [e["cl"] for e in evals] + [s["target_cl"] - s["cl_tol"], s["target_cl"] + s["cl_tol"]]
    x0, x1, y0, y1 = min(cds), max(cds), min(cls), max(cls)
    px, py = (x1 - x0) * 0.08 or 0.001, (y1 - y0) * 0.08 or 0.01
    return {"wing": wing, "polar": (x0 - px, x1 + px, y0 - py, y1 + py)}


def _draw_wing(ax, export: dict, fr: Frame, fx: dict, t: dict, b: tuple, mono: str) -> None:
    ax.set_facecolor(t["bg"])
    ax.set_xlim(b[0], b[1])
    ax.set_ylim(b[2], b[3])
    ax.set_aspect("equal")
    ax.axis("off")
    ax.plot([-0.18, 1.06], [0, 0], color=t["line"], lw=1, ls=(0, (2, 5)))
    ax.annotate("", xy=(-0.05, 0), xytext=(-0.18, 0), arrowprops={"arrowstyle": "-|>", "color": t["ink2"], "lw": 1.4})
    ax.text(-0.18, 0.03, "flow", color=t["ink3"], fontsize=8.5)
    start = np.asarray(export["outlines"][export["start_cid"]], dtype=float)
    ax.plot(*np.vstack([start, start[:1]]).T, color=t["ghost"], lw=1.3, ls=(0, (5, 4)))
    xy = shape(export, fr)
    # above the dashed start outline (lines draw over patches by default)
    ax.add_patch(Polygon(xy, closed=True, facecolor=t["accent"], alpha=0.16, lw=0, zorder=3))
    ax.add_patch(Polygon(xy, closed=True, fill=False, edgecolor=t["accent"], lw=2, joinstyle="round", zorder=3))
    # downforce arrow below the quarter chord, length ∝ |Cl| of the recorded frame; dashed tick = target
    band = xy[(xy[:, 0] > 0.15) & (xy[:, 0] < 0.4)]
    y_top = (band[:, 1].min() if len(band) else xy[:, 1].min()) - 0.02
    x_a = 0.27
    target = abs(export["spec"]["target_cl"]) * ARROW_K
    ax.plot([x_a - 0.06, x_a + 0.06], [y_top - target] * 2, color=t["good"], lw=1.5, ls=(0, (4, 3)))
    ax.text(
        x_a + 0.08,
        y_top - target,
        f"target {spec_num(export['spec']['target_cl'])}",
        color=t["ink3"],
        fontsize=8.5,
        va="center",
        family=mono,
    )
    length = fx["abs_cl"] * ARROW_K
    if length > 0.02:
        ax.annotate(
            "",
            xy=(x_a, y_top - length),
            xytext=(x_a, y_top),
            arrowprops={"arrowstyle": "-|>,head_width=0.35,head_length=0.7", "color": t["accent"], "lw": 2.6},
        )
    if fx["interpolated"]:
        ax.text(
            0.0,
            1.0,
            f"interpolated shape → generation {fx['toward']}",
            transform=ax.transAxes,
            color=t["ink3"],
            fontsize=8.5,
            va="top",
            style="italic",
        )


def _draw_polar(ax, export: dict, fr: Frame, t: dict, b: tuple, mono: str) -> None:
    s = export["spec"]
    ax.set_facecolor(t["bg"])
    x0, x1, y0, y1 = b
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)  # more negative Cl (more downforce) on top, as in the viewer
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["line2"])
    ax.tick_params(colors=t["ink3"], labelsize=8, length=0, pad=4)
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_family(mono)
    ax.grid(color=t["line"], lw=0.8)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(4))
    ax.yaxis.set_major_locator(ticker.MaxNLocator(4))
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: ("−" if v < 0 else "") + f"{abs(v):.1f}"))
    ax.set_xlabel("Cd (drag) →", color=t["ink3"], fontsize=8.5, labelpad=3)
    ax.set_ylabel("Cl (downforce ↑)", color=t["ink3"], fontsize=8.5, labelpad=3)
    bx0 = max(x0, 0.0)
    ax.add_patch(
        Rectangle(
            (bx0, s["target_cl"] - s["cl_tol"]),
            s["cd_max"] - bx0,
            2 * s["cl_tol"],
            facecolor=t["good"],
            alpha=t["target_alpha"],
            lw=0,
        )
    )
    ax.add_patch(
        Rectangle(
            (bx0, s["target_cl"] - s["cl_tol"]),
            s["cd_max"] - bx0,
            2 * s["cl_tol"],
            fill=False,
            edgecolor=t["good"],
            lw=1.3,
            ls=(0, (5, 3)),
        )
    )
    ax.text(
        s["cd_max"],
        s["target_cl"] - s["cl_tol"],
        "target box ",
        color=t["good_ink"],
        fontsize=8,
        weight="semibold",
        ha="right",
        va="bottom",
    )
    shown = recorded(export)[: fr.i + 1]
    trail = [head(g) for g in shown if head(g)["cl"] is not None and head(g)["cd"] is not None]
    if trail:
        ax.plot([e["cd"] for e in trail], [e["cl"] for e in trail], color=t["ink3"], lw=1.3, alpha=0.55)
    for g in shown:
        for e in g["evals"]:
            if e["cl"] is None or e["cd"] is None:
                continue
            colour = t[KIND_COLOUR[status_of(e)[1]]]
            inner = e.get("inner_optimizer")
            ax.scatter(
                e["cd"],
                e["cl"],
                s=(14 if inner else 38) if e["solver"] == "neuralfoil" else 58,
                marker="o" if e["solver"] == "neuralfoil" else "s",
                color=colour,
                edgecolors=t["bg"],
                linewidths=1.4,
                alpha=0.55 if inner else 1.0,
                zorder=3,
            )
    cur = head(shown[-1])
    if cur["cl"] is not None and cur["cd"] is not None:
        ax.scatter(cur["cd"], cur["cl"], s=230, facecolors="none", edgecolors=t["ink"], linewidths=1.7, zorder=4)
    handles = [
        Line2D([], [], ls="", marker="o", color=t["good"], ms=5.5, label="pass"),
        Line2D([], [], ls="", marker="o", color=t["warning"], ms=5.5, label="target miss"),
        Line2D([], [], ls="", marker="o", color=t["critical"], ms=5.5, label="failure"),
        Line2D([], [], ls="", marker="o", mfc="none", color=t["ink2"], ms=5.5, label="NeuralFoil"),
        Line2D([], [], ls="", marker="s", mfc="none", color=t["ink2"], ms=5.5, label="XFoil"),
    ]
    leg = ax.legend(
        handles=handles,
        loc="lower right",
        bbox_to_anchor=(1.0, 1.0),
        ncol=5,
        frameon=False,
        fontsize=7.5,
        handletextpad=0.2,
        columnspacing=0.8,
        borderaxespad=0.2,
    )
    for txt in leg.get_texts():
        txt.set_color(t["ink2"])


def _chain(fig, prev, text: str, pad: float, dy: float = 0, **kw) -> Annotation:
    """A text placed right after `prev`, bottoms aligned (positions follow the rendered widths)."""
    a = Annotation(text, xy=(1, 0), xycoords=prev, xytext=(pad, dy), textcoords="offset points", va="bottom", **kw)
    fig.add_artist(a)
    return a


def _draw_header_footer(fig, fx: dict, t: dict, mono: str) -> None:
    y = 0.865
    lab = fig.text(0.03, y + 0.008, "GENERATION", color=t["ink3"], fontsize=8.5, weight="semibold", va="bottom")
    num = _chain(fig, lab, str(fx["gen"]), 6, dy=-3, color=t["ink"], fontsize=20, weight="semibold", family=mono)
    of = _chain(fig, num, f"of {fx['of']}", 5, dy=3, color=t["ink3"], fontsize=10)
    tint, edge = t[KIND_COLOUR[fx["kind"]]], t[KIND_COLOUR[fx["kind"]]]
    pill = {"boxstyle": "round,pad=0.38,rounding_size=0.25", "fc": tint + "1f", "ec": edge, "lw": 1}
    _chain(
        fig,
        of,
        fx["status"],
        14,
        dy=1,
        color=t[KIND_INK[fx["kind"]]],
        fontsize=9,
        weight="bold",
        family=mono,
        bbox=pill,
    )
    # readouts, right-aligned columns: label above, value below (green inside the target, as in the viewer)
    for x, k, v, ok in (
        (0.70, "CL", fx["cl"], fx["cl_ok"]),
        (0.835, "CD", fx["cd"], fx["cd_ok"]),
        (0.97, "SOLVER", fx["solver"], False),
    ):
        fig.text(x, y + 0.062, k, color=t["ink3"], fontsize=7.5, ha="right", va="bottom", weight="semibold")
        colour = t["good_ink"] if ok else t["ink"]
        fig.text(x, y, v, color=colour, fontsize=13, ha="right", va="bottom", family=mono, weight="semibold")
    fig.add_artist(Line2D([0.03, 0.97], [0.098, 0.098], transform=fig.transFigure, color=t["line"], lw=1))
    brand = fig.text(0.03, 0.032, "Aeroptimize", color=t["accent"], fontsize=9.5, weight="bold", va="bottom")
    _chain(fig, brand, "AI agents design a race-car wing", 7, color=t["ink2"], fontsize=9)
    kind = fx["footer_kind"]
    fig.text(
        0.97,
        0.032,
        ("✓ " if kind == "pass" else "") + fx["footer"],
        color=t[KIND_INK[kind]] if kind else t["ink2"],
        fontsize=9.5 if kind else 9,
        weight="bold" if kind else "normal",
        ha="right",
        va="bottom",
    )


def render_frames(export: dict, theme: str = "light", dpi: int = 100, frames: list[Frame] | None = None):
    """RGB arrays for `frames` (default: `plan(export)`), and their durations in ms."""
    t = THEMES[theme]
    sans, mono = _fonts()
    b = _bounds(export)
    frames = plan(export) if frames is None else frames
    imgs = []
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)  # weight fallbacks of the fallback fonts
    with plt.rc_context({"font.family": [sans, "DejaVu Sans"], "axes.unicode_minus": False}):
        fig = plt.figure(figsize=SIZE_IN, dpi=dpi, facecolor=t["bg"])
        try:
            for fr in frames:
                fig.clear()
                fig.set_facecolor(t["bg"])
                fx = facts(export, fr)
                _draw_wing(fig.add_axes((0.02, 0.15, 0.54, 0.66)), export, fr, fx, t, b["wing"], mono)
                _draw_polar(fig.add_axes((0.655, 0.235, 0.315, 0.5)), export, fr, t, b["polar"], mono)
                _draw_header_footer(fig, fx, t, mono)
                fig.canvas.draw()
                imgs.append(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
        finally:
            plt.close(fig)
    return imgs, [fr.ms for fr in frames]


def _indices(img: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Exact nearest-palette index per pixel (Pillow's palette conversion is approximate by a level or two)."""
    code = (img[..., 0].astype(np.int32) << 16) | (img[..., 1].astype(np.int32) << 8) | img[..., 2]
    uniq, inv = np.unique(code.ravel(), return_inverse=True)
    rgb = np.stack([(uniq >> 16) & 255, (uniq >> 8) & 255, uniq & 255], axis=1)
    d = ((rgb[:, None, :] - palette[None, :, :].astype(np.int32)) ** 2).sum(-1)
    return d.argmin(1)[inv].reshape(img.shape[:2]).astype(np.uint8)


def save_gif(
    imgs: list[np.ndarray], durations: list[int], path: Path, colors: int = 128, keep: tuple[str, ...] = ()
) -> Path:
    """One shared palette for every frame (no colour flicker), no dithering (flat colours stay flat). The `keep`
    colours (hex) are reserved exactly, so a status colour absent from the sampled frames is not remapped."""
    sample = imgs[:: max(1, len(imgs) // 8)] + [imgs[-1]]
    reserved = [tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in dict.fromkeys(keep)]
    montage = Image.fromarray(np.vstack(sample))
    adaptive = montage.quantize(
        colors=colors - len(reserved), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    n = len(adaptive.getcolors(colors) or []) or colors - len(reserved)
    palette = np.array(adaptive.getpalette()[: 3 * n], dtype=np.uint8).reshape(-1, 3)
    palette = np.vstack([palette, np.array(reserved, dtype=np.uint8).reshape(-1, 3)])
    flat = palette.ravel().tolist() + [0] * (768 - palette.size)
    frames = []
    for img in imgs:
        im = Image.frombytes("P", (img.shape[1], img.shape[0]), _indices(img, palette).tobytes())
        im.putpalette(flat)
        frames.append(im)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=1)
    return path


def write_gif(export: dict | str | Path, path: str | Path, theme: str = "light", dpi: int = 100, **plan_kw) -> Path:
    """The replay GIF of one export (`viewer/runs/<name>.json`) in one theme."""
    export = export if isinstance(export, dict) else load(export)
    imgs, ms = render_frames(export, theme, dpi, plan(export, **plan_kw))
    keep = tuple(v for v in THEMES[theme].values() if isinstance(v, str))
    return save_gif(imgs, ms, Path(path), keep=keep)
