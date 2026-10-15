"""Deterministic images for the vision Critic (milestone 3, BLUEPRINT §3 "Multimodal critique").

Every image has the same frame (fixed axes and ranges, fixed colours), overlays the candidate on its parent
(the design it was derived from), and prints the key numbers as text, so a vision model compares like with
like. At T0/T1 (NeuralFoil, XFoil) there are no residuals, contours or streamlines; the 2D equivalents are:

- "cp": Cp(x/c) on both surfaces (-Cp up). Separation shows as a pressure plateau before the TE, a leading-
  edge spike as a sharp suction peak, a geometry defect as a local kink.
- "boundary_layer": suction-side shape factor H(x/c) with the screen's separation limits, and at XFoil the
  skin friction Cf(x/c) (Cf < 0 = reversed flow).
- "section": the section in the car frame (side view) with the rulebook's height, overhang and
  head-restraint lines.

Surface data: `swarm.critic.surface.surface_data` (XFoil's boundary-layer dump, or one NeuralFoil call).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from swarm.cad.build import placed_mm  # noqa: E402
from swarm.cad.regulations import RULEBOOKS, le_radius_mm  # noqa: E402
from swarm.critic.numeric import VALIDATION  # noqa: E402
from swarm.critic.surface import surface_data  # noqa: E402
from swarm.state import CFDResult, DesignSpec, WingParams  # noqa: E402

IMAGES = ("cp", "boundary_layer", "section")
SIZE = (8.0, 4.5)  # inches at DPI: 800 x 450 px, about 500 input tokens per image
DPI = 100
CAND, PARENT, RULE, SEP = "#0F6E56", "0.55", "#B3261E", "#E4572E"
CP_RANGE = (-1.5, 7.0)  # -Cp axis, fixed
H_RANGE = (1.0, 6.0)
CF_RANGE = (-2.0, 12.0)  # Cf x 1000


def _label(params: WingParams, result: CFDResult | None, role: str) -> str:
    if result is None or result.cl is None:
        return f"{role} {params.cid}: no result"
    lvl = f" L{result.solver_level}" if result.solver_level is not None else ""
    return (
        f"{role} {params.cid} [{result.fidelity}{lvl}]  alpha {params.alpha_deg:g}°  "
        f"Cl {result.cl:.3f}  Cd {result.cd:.4f}"
    )


def _clip_note(ax, arrays: list[np.ndarray], lo: float, hi: float, what: str) -> None:
    vals = np.concatenate([a[np.isfinite(a)] for a in arrays]) if arrays else np.array([])
    if len(vals) and (vals.min() < lo or vals.max() > hi):
        ax.text(
            0.99,
            0.02,
            f"{what} off scale: {vals.min():.2f} to {vals.max():.2f}",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=8,
            color=RULE,
        )


def _cp_image(cand: dict | None, par: dict | None, title: list[str], path: Path) -> None:
    fig, ax = plt.subplots(figsize=SIZE, dpi=DPI)
    arrays = []
    for data, color, ls, who in ((par, PARENT, "--", "parent"), (cand, CAND, "-", "candidate")):
        if data is None:
            continue
        for side, mk in (("suction", "o"), ("pressure", "s")):
            d = data[side]
            ax.plot(
                d["x"],
                -d["cp"],
                ls=ls,
                color=color,
                lw=1.6 if who == "candidate" else 1.1,
                marker=mk,
                ms=2.5 if who == "candidate" else 0,
                label=f"{who} {side} side",
            )
            arrays.append(-d["cp"])
    ax.axhline(0, color="0.8", lw=0.8)
    ax.set_xlim(0, 1)
    ax.set_ylim(*CP_RANGE)
    ax.set_xlabel("x/c")
    ax.set_ylabel("-Cp")
    _clip_note(ax, arrays, *CP_RANGE, "-Cp")
    if cand is None:
        ax.text(0.5, 0.5, "no surface data for the candidate", transform=ax.transAxes, ha="center", color=RULE)
    if arrays:
        ax.legend(loc="upper right", fontsize=7, ncol=2)
    ax.set_title("\n".join(title), fontsize=8, loc="left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _bl_image(cand: dict | None, par: dict | None, result: CFDResult | None, title: list[str], path: Path) -> None:
    has_cf = cand is not None and "cf" in cand["suction"]
    fig, axes = plt.subplots(1, 2 if has_cf else 1, figsize=SIZE, dpi=DPI, squeeze=False)
    ax = axes[0][0]
    hs = []
    for data, color, ls, who in ((par, PARENT, "--", "parent"), (cand, CAND, "-", "candidate")):
        if data is not None:
            ax.plot(data["suction"]["x"], data["suction"]["h"], ls=ls, color=color, label=f"{who}")
            hs.append(data["suction"]["h"])
    ax.axhline(VALIDATION.screen_h_sep, color=RULE, lw=0.9, ls=":")
    ax.text(
        0.01,
        VALIDATION.screen_h_sep + 0.05,
        f"H {VALIDATION.screen_h_sep} (screen: TE separation at alpha)",
        fontsize=7,
        color=RULE,
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(*H_RANGE)
    ax.set_xlabel("x/c")
    ax.set_ylabel("suction-side shape factor H")
    _clip_note(ax, hs, *H_RANGE, "H")
    if hs:
        ax.legend(loc="upper left", fontsize=7)
    if has_cf:
        ax2 = axes[0][1]
        for data, color, ls, who in ((par, PARENT, "--", "parent"), (cand, CAND, "-", "candidate")):
            if data is not None and "cf" in data["suction"]:
                ax2.plot(data["suction"]["x"], 1000 * data["suction"]["cf"], ls=ls, color=color, label=who)
        ax2.axhline(0, color=RULE, lw=0.9, ls=":")
        sep = result.bl.te_separation_xc if result is not None and result.bl else None
        if sep is not None:
            ax2.axvspan(sep, 1.0, color=SEP, alpha=0.15, lw=0)
            ax2.text(sep, CF_RANGE[1] * 0.9, f" TE separation from x/c {sep:.2f}", fontsize=7, color=SEP)
        ax2.set_xlim(0, 1)
        ax2.set_ylim(*CF_RANGE)
        ax2.set_xlabel("x/c")
        ax2.set_ylabel("suction-side Cf x 1000 (< 0: reversed flow)")
        _clip_note(ax2, [1000 * cand["suction"]["cf"]], *CF_RANGE, "Cf x 1000")
    elif cand is not None:
        ax.text(0.99, 0.95, "Cf not available at NeuralFoil", transform=ax.transAxes, ha="right", fontsize=7)
    fig.suptitle("\n".join(title), fontsize=8, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _section_image(params: WingParams, parent: WingParams | None, spec: DesignSpec, title: list[str], path: Path):
    car = spec.car
    fig, ax = plt.subplots(figsize=SIZE, dpi=DPI)
    for p, color, ls, who in ((parent, PARENT, "--", "parent"), (params, CAND, "-", "candidate")):
        if p is None:
            continue
        xy = placed_mm(p, car)["main"]
        ax.plot(xy[:, 0], xy[:, 1], ls=ls, color=color, lw=1.5 if who == "candidate" else 1.0, label=who)
    notes = []
    if spec.rulebook in RULEBOOKS:
        rb = RULEBOOKS[spec.rulebook]
        ax.axhline(rb.rear_max_height.value, color=RULE, lw=0.9, ls=":")
        ax.text(
            car.head_restraint_x + 20,
            rb.rear_max_height.value - 25,
            f"{rb.rear_max_height.rule}: max height {rb.rear_max_height.value:g} mm",
            fontsize=7,
            color=RULE,
        )
        x_lim = car.rear_tire_rear_x + rb.max_behind_rear_tire.value
        ax.axvline(x_lim, color=RULE, lw=0.9, ls=":")
        ax.text(
            x_lim - 5,
            820,
            f"{rb.max_behind_rear_tire.rule}: {rb.max_behind_rear_tire.value:g} mm behind tires",
            fontsize=7,
            color=RULE,
            ha="right",
            rotation=90,
        )
        notes.append(
            f"LE radius {le_radius_mm(params.main_thickness, car.chord_mm):.1f} mm "
            f"(min {rb.le_radius_min.value:g}, {rb.le_radius_min.rule})"
        )
    else:
        notes.append("rulebook check off")
    ax.axvline(car.rear_tire_rear_x, color="0.7", lw=0.8)
    ax.text(car.rear_tire_rear_x - 5, 820, "rear of rear tires", fontsize=7, color="0.5", ha="right", rotation=90)
    ax.axvline(car.head_restraint_x, color="0.7", lw=0.8)
    ax.text(car.head_restraint_x + 5, 820, "head-restraint plane", fontsize=7, color="0.5", rotation=90)
    ax.set_xlim(car.head_restraint_x - 50, car.rear_tire_rear_x + 400)
    ax.set_ylim(800, 1250)
    ax.set_aspect("equal")
    ax.set_xlabel("x rearward from the front axle (mm)")
    ax.set_ylabel("height above ground (mm)")
    ax.legend(loc="lower left", fontsize=7)
    ax.set_title("\n".join(title + ["; ".join(notes) + "  (placeholder car geometry)"]), fontsize=8, loc="left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def render(
    params: WingParams,
    result: CFDResult | None,
    spec: DesignSpec,
    out_dir: str | Path,
    parent: tuple[WingParams, CFDResult | None] | None = None,
    surface: dict | None = None,
    parent_surface: dict | None = None,
) -> dict[str, str]:
    """Write cp.png, boundary_layer.png and section.png to out_dir; returns {image: path}.

    `surface` / `parent_surface` override the solver data (the Critic failure zoo injects defects this way).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cand = surface if surface is not None else surface_data(params, spec, result)
    pp, pr = parent if parent else (None, None)
    par = parent_surface if parent_surface is not None else (surface_data(pp, spec, pr) if pp else None)
    title = [_label(params, result, "candidate")]
    if pp is not None:
        title.append(_label(pp, pr, "parent   "))
    src = f"surface data: {cand['source']}" if cand else "surface data: none"
    paths = {k: out / f"critic_{k}.png" for k in IMAGES}
    _cp_image(cand, par, title + [src], paths["cp"])
    _bl_image(cand, par, result, title, paths["boundary_layer"])
    _section_image(params, pp, spec, title[:1] + ([title[1]] if len(title) > 1 else []), paths["section"])
    return {k: str(v) for k, v in paths.items()}
