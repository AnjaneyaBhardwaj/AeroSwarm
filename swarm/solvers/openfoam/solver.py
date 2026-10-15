"""T2: 2D OpenFOAM evaluation of a design (`of2d`): O-grid, checkMesh, simpleFoam (k-omega SST), forces from the
fields, convergence measures. The solver frame is the upright section (as at T0/T1); race-car Cl is negated.

Convergence is judged by the numeric validator from what this records (BLUEPRINT §2 "Convergence criteria"):
initial-residual drop in orders of magnitude for p and U (`residual_drop_orders`), and the relative standard
deviation of Cl and Cd over the last 300 iterations of the written history (`coeff_rel_std_window`).
"""

from __future__ import annotations

import math
import re
import shutil
import time
from pathlib import Path

import numpy as np

from swarm.cad.build import main_section
from swarm.solvers.openfoam import exec as foam
from swarm.solvers.openfoam import forces
from swarm.solvers.openfoam.case import SolverOverrides, write_case
from swarm.solvers.openfoam.mesh import MeshSpec, o_grid, write_polymesh
from swarm.solvers.openfoam.monitor import Monitor
from swarm.state import BoundaryLayerSummary, CFDResult, DesignSpec, WingParams

# Project defaults, from the NACA 0012 validation (docs/OPENFOAM.md): a 100-chord far field.
DEFAULT_MESH = MeshSpec(farfield=100.0, max_step=4.0)
COEFF_WINDOW = 300  # iterations for the Cl / Cd relative standard deviation
_RES = re.compile(r"Solving for (\w+), Initial residual = ([-+\deE.naif]+)")
_TIME = re.compile(r"^Time = (\d+)")


def residual_history(log: str | Path) -> dict[str, list[float]]:
    """Initial residual per iteration and field (the first solve of each field in an iteration)."""
    out: dict[str, list[float]] = {}
    seen: set[str] = set()
    for line in Path(log).read_text().splitlines():
        if _TIME.match(line):
            seen = set()
            continue
        m = _RES.search(line)
        if m and m[1] not in seen:
            seen.add(m[1])
            try:
                out.setdefault(m[1], []).append(float(m[2]))
            except ValueError:
                out.setdefault(m[1], []).append(float("nan"))
    return out


def drop_orders(h: list[float]) -> float | None:
    """Orders of magnitude between the largest early initial residual and the last one."""
    if len(h) < 2:
        return None
    first = max(h[: max(1, min(10, len(h)))])
    last = h[-1]
    if not (math.isfinite(first) and math.isfinite(last)) or first <= 0 or last <= 0:
        return None
    return round(math.log10(first / last), 3)


def parse_checkmesh(log: str | Path) -> dict:
    text = Path(log).read_text()

    def num(pat: str) -> float | None:
        m = re.search(pat, text)
        return float(m[1]) if m else None

    cells = re.search(r"^\s*cells:\s+(\d+)", text, re.M)
    return {
        "ok": "Mesh OK." in text,
        "cells": int(cells[1]) if cells else None,
        "max_non_ortho": num(r"Mesh non-orthogonality Max: ([\d.eE+-]+)"),
        "max_skewness": num(r"Max skewness = ([\d.eE+-]+)"),
        "max_aspect": num(r"Max aspect ratio = ([\d.eE+-]+)"),
        "failed_checks": int(m[1]) if (m := re.search(r"Failed (\d+) mesh checks", text)) else 0,
    }


def rel_std_window(hist: list[tuple[int, float, float]], window: int = COEFF_WINDOW) -> dict[str, float]:
    if not hist:
        return {}
    last = hist[-1][0]
    win = [h for h in hist if h[0] >= last - window]
    if len(win) < 3:
        return {}
    out = {}
    for k, idx in (("cl", 1), ("cd", 2)):
        v = np.array([h[idx] for h in win])
        m = abs(v.mean())
        out[k] = float(v.std() / m) if m > 0 else float("inf")
    return out


def suction_bl(c: dict, upright_cl: float) -> BoundaryLayerSummary:
    """TE separation from the suction-side Cf of the wall-adjacent cells (as XFoil's Cf, swarm.solvers.xfoil)."""
    from swarm.solvers.xfoil import classify_separation

    s = forces.surface(c, upright_cl)["suction"]
    # the last cell is the trailing-edge corner next to the blunt base, where the flow turns around the corner;
    # its Cf says nothing about separation (XFoil's dump has no such cell)
    te_sep, bubbles = classify_separation(np.asarray(s["x"])[:-1], np.asarray(s["cf"])[:-1])
    return BoundaryLayerSummary(
        suction_side="upper" if upright_cl >= 0 else "lower",
        cf_te=float(s["cf"][-1]),
        te_separation_xc=te_sep,
        bubbles=bubbles,
        source="none",
    )


def evaluate(
    params: WingParams,
    spec: DesignSpec,
    run_dir: str | Path,
    overrides: SolverOverrides | None = None,
    mesh: MeshSpec = DEFAULT_MESH,
    tag: str = "L0",
    coords: np.ndarray | None = None,
    timeout: float = 3600.0,
) -> CFDResult:
    """Mesh, solve and post-process one design; never raises for a solver failure (status says what happened)."""
    t0 = time.perf_counter()
    overrides = overrides or SolverOverrides()
    case = Path(run_dir) / params.cid / f"of2d_{tag}"
    shutil.rmtree(case, ignore_errors=True)
    case.mkdir(parents=True)
    base = {"cid": params.cid, "fidelity": "of2d", "artifacts": {"case": str(case)}}
    if not foam.available():
        return CFDResult(**base, status="mesh_failed", failure_signature="openfoam_missing")
    grid = o_grid(main_section(params) if coords is None else coords, mesh)
    info = write_polymesh(grid, case, mesh.span)
    write_case(case, params.alpha_deg, spec.reynolds, mesh.span, overrides)
    cm = foam.run("checkMesh", case, timeout=600)
    m = {**info, **parse_checkmesh(cm.log_path), "first_cell": mesh.first_cell, "farfield": mesh.farfield}
    if not m["ok"]:
        return CFDResult(
            **base, status="mesh_failed", failure_signature=f"checkMesh:{m['failed_checks']}_failed", mesh=m,
            log_path=cm.log_path, wall_s=time.perf_counter() - t0,
        )  # fmt: skip
    if overrides.potential_init:
        pf = foam.run("potentialFoam", case, args=("-writep",), timeout=600)
        if pf.returncode != 0:
            return CFDResult(
                **base, status="diverged", failure_signature="potentialFoam_failed", mesh=m, log_path=pf.log_path,
                wall_s=time.perf_counter() - t0,
            )  # fmt: skip
    mon = Monitor()
    out = foam.run("simpleFoam", case, timeout=timeout, on_line=mon.feed)
    res_hist = residual_history(out.log_path)
    drops = {k: v for k, v in (("p", drop_orders(res_hist.get("p", []))), ("U", _u_drop(res_hist))) if v is not None}
    common = {**base, "mesh": m, "log_path": out.log_path, "residual_drop_orders": drops}
    signature = out.signature or (mon.post_mortem(out.log_path) if out.returncode != 0 else None)
    if signature or out.returncode != 0:
        status = "timeout" if (signature or "").startswith("timeout") else "diverged"
        return CFDResult(
            **common, status=status, failure_signature=signature or f"exit_{out.returncode}",
            wall_s=time.perf_counter() - t0,
        )  # fmt: skip
    dirs = forces.time_dirs(case)
    if not dirs:
        return CFDResult(**common, status="not_converged", failure_signature="no_fields_written")
    c = forces.coefficients(case, dirs[-1][1], params.alpha_deg, spec.reynolds, mesh.span)
    hist = forces.history(case, params.alpha_deg, spec.reynolds, mesh.span)
    finite = all(math.isfinite(v) for v in (c["cl"], c["cd"], c["cm"]))
    if not finite:
        return CFDResult(**common, status="diverged", failure_signature="nonfinite_coeffs")
    yp = c["yplus"]
    return CFDResult(
        **common,
        status="converged",
        cl=-c["cl"],  # race-car convention
        cd=c["cd"],
        cm=-c["cm"],
        coeff_rel_std_window=rel_std_window(hist),
        yplus=(float(yp.min()), float(yp.mean()), float(yp.max())),
        bl=suction_bl(c, c["cl"]),
        wall_s=time.perf_counter() - t0,
    )


def _u_drop(res_hist: dict[str, list[float]]) -> float | None:
    vals = [d for k in ("Ux", "Uy") if (d := drop_orders(res_hist.get(k, []))) is not None]
    return min(vals) if vals else None
