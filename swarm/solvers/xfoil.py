"""T1: XFoil wrapper with its own recovery ladder (BLUEPRINT §4).

XFoil runs headless: every script starts with `PLOP / G` (graphics off), and
the subprocess gets no DISPLAY. Build the binary with
`scripts/install_xfoil.sh`; the stock Debian package aborts with SIGFPE.

Ladder levels (code guarantees each is tried at most once per candidate):
  L0 direct solve, 100 iterations
  L1 300 iterations
  L2 alpha continuation from 0° in 0.5° steps
  L3 alpha continuation, 240 panels
After L3 the graph falls back to NeuralFoil with `fallback_from="xfoil"`.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from swarm.state import BoundaryLayerSummary, CFDResult, DesignSpec, WingParams

MAX_LEVEL = 3
LEVELS: dict[int, dict] = {
    0: {"n_iter": 100, "npanel": 160, "continuation": False},
    1: {"n_iter": 300, "npanel": 160, "continuation": False},
    2: {"n_iter": 300, "npanel": 160, "continuation": True},
    3: {"n_iter": 300, "npanel": 240, "continuation": True},
}
LEVEL_NAMES = {0: "direct", 1: "more_iterations", 2: "alpha_continuation", 3: "continuation_more_panels"}

POLAR = "polar.txt"
DUMP = "bl_dump.txt"
CPWR = "cp.txt"
STDOUT = "xfoil.log"


def xfoil_bin() -> str | None:
    return os.environ.get("XFOIL_BIN") or shutil.which("xfoil")


def xfoil_available() -> bool:
    b = xfoil_bin()
    return bool(b) and os.access(b, os.X_OK)


def alpha_schedule(alpha: float, continuation: bool, step: float = 0.5) -> list[float]:
    if not continuation or abs(alpha) < step:
        return [alpha]
    s = step if alpha > 0 else -step
    seq = list(np.arange(0.0, alpha, s))
    return [round(a, 3) for a in seq] + [alpha]


def build_script(coords_name: str, re: float, alphas: list[float], n_iter: int, npanel: int, ncrit: float = 9.0) -> str:
    s = [
        "PLOP",
        "G",
        "",  # graphics OFF: must come first
        f"LOAD {coords_name}",
        "PPAR",
        f"N {npanel}",
        "",
        "",
        "OPER",
        f"VISC {re:.0f}",
        "VPAR",
        f"N {ncrit:g}",
        "",
        f"ITER {n_iter}",
        "PACC",
        POLAR,
        "",
    ]
    s += [f"ALFA {a:.3f}" for a in alphas]
    s += [f"DUMP {DUMP}", f"CPWR {CPWR}", "PACC", "", "QUIT", ""]
    return "\n".join(s)


def _exec(argv: list[str], script: str, cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}  # never open a window
    return subprocess.run(argv, input=script, text=True, capture_output=True, timeout=timeout, cwd=cwd, env=env)


# ---------------------------------------------------------------- parsing


def _num(tok: str) -> float:
    """Float, with Fortran overflow fields (`*******`) read as NaN.

    Our XFoil build has FP traps off (scripts/install_xfoil.sh), so a blown-up
    solve prints NaN / Infinity / asterisks instead of aborting.
    """
    if tok and set(tok.lstrip("+-")) == {"*"}:
        return math.nan
    return float(tok)


def all_finite(*vals: float | None) -> bool:
    """True when every non-None value is a finite float."""
    return all(v is None or math.isfinite(v) for v in vals)


def parse_polar(text: str, finite_only: bool = True) -> list[dict[str, float]]:
    """Rows after the dashed header line. Tolerates build-specific header length.

    Rows with a non-finite value (NaN, ±inf, Fortran `****`) are dropped unless
    `finite_only=False`; the wrapper uses the raw rows only to label the failure.
    """
    lines = text.splitlines()
    start = next((i + 1 for i, line in enumerate(lines) if line.strip().startswith("---")), None)
    if start is None:
        return []
    keys = ("alpha", "cl", "cd", "cdp", "cm", "top_xtr", "bot_xtr")
    rows = []
    for line in lines[start:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            vals = [_num(p) for p in parts[:7]]
        except ValueError:
            continue
        if finite_only and not all_finite(*vals):
            continue
        rows.append(dict(zip(keys, vals, strict=False)))
    return rows


@dataclass
class Surface:
    x: np.ndarray  # LE → TE
    cf: np.ndarray


class NonFiniteDump(ValueError):
    """The BL dump has NaN/inf on the airfoil surface (x or Cf)."""


@dataclass
class BLDump:
    upper: Surface
    lower: Surface
    raw: np.ndarray = field(repr=False)


def parse_dump(text: str) -> BLDump | None:
    """XFoil DUMP: surface rows (≥ 8 columns incl. Cf) then wake rows.

    Surface rows run TE(upper) → LE → TE(lower). Wake rows follow; they have
    fewer columns in 6.99 and always Cf = 0, so we cut at the first wake row
    (x beyond the lower TE after the LE).

    Raises `NonFiniteDump` if any surface x or Cf is NaN/inf: a separation
    verdict must never rest on a blown-up boundary layer.
    """
    rows = []
    for line in text.splitlines():
        if line.lstrip().startswith("#") or not line.strip():
            continue
        parts = line.split()
        try:
            rows.append([_num(p) for p in parts[:8]] + [len(parts)])
        except ValueError:
            continue
    if len(rows) < 10:
        return None
    a = np.array([r for r in rows if len(r) == 9])
    ncols = a[:, 8]
    surf_cols = ncols[0]
    # surface = leading block with the full column count
    n_surf = int(np.argmax(ncols != surf_cols)) if np.any(ncols != surf_cols) else len(a)
    s = a[:n_surf]
    if not np.all(np.isfinite(s[:, [1, 6]])):
        raise NonFiniteDump(f"{int(np.sum(~np.isfinite(s[:, [1, 6]])))} non-finite x/Cf values on the surface")
    x = s[:, 1]
    ile = int(np.argmin(x))
    # guard: if the column-count heuristic failed, cut where x exceeds 1 after the LE
    after = np.where(x[ile:] > x[: ile + 1].max() + 1e-6)[0]
    if len(after):
        s = s[: ile + after[0]]
        x = s[:, 1]
    up = s[: ile + 1][::-1]
    lo = s[ile:]
    return BLDump(upper=Surface(x=up[:, 1], cf=up[:, 6]), lower=Surface(x=lo[:, 1], cf=lo[:, 6]), raw=s)


def reversed_runs(x: np.ndarray, cf: np.ndarray) -> list[tuple[int, int]]:
    """Index ranges [i0, i1] (inclusive) of contiguous Cf < 0 stations, LE → TE."""
    neg = cf < 0
    runs, i = [], 0
    while i < len(neg):
        if neg[i]:
            j = i
            while j + 1 < len(neg) and neg[j + 1]:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return runs


def classify_separation(
    x: np.ndarray, cf: np.ndarray, min_stations: int = 2
) -> tuple[float | None, list[tuple[float, float]]]:
    """TE separation = Cf < 0 on the suction side that persists to the trailing edge.

    A reversed run that reaches the last (TE) station and spans at least
    `min_stations` stations is TE separation; its start x/c is returned.
    Every other reversed run reattaches before the TE and is a laminar
    separation bubble (start, end) — recorded, but not TE separation.
    """
    te_sep, bubbles = None, []
    last = len(cf) - 1
    for i0, i1 in reversed_runs(x, cf):
        if i1 == last and (i1 - i0 + 1) >= min_stations:
            te_sep = float(x[i0])
        else:
            bubbles.append((float(x[i0]), float(x[min(i1 + 1, last)])))
    return te_sep, bubbles


def summarize_bl(dump: BLDump, upright_cl: float, transition: dict[str, float]) -> BoundaryLayerSummary:
    side = "upper" if upright_cl >= 0 else "lower"
    surf = dump.upper if side == "upper" else dump.lower
    te_sep, bubbles = classify_separation(surf.x, surf.cf)
    return BoundaryLayerSummary(
        suction_side=side,
        cf_te=float(surf.cf[-1]),
        te_separation_xc=te_sep,
        bubbles=bubbles,
        transition_xc=transition.get("top_xtr" if side == "upper" else "bot_xtr"),
        source="xfoil_cf",
    )


# ---------------------------------------------------------------- running


def run_xfoil(
    coords_path: str | Path,
    re: float,
    alpha: float,
    level: int,
    work_dir: str | Path,
    timeout: float = 30.0,
    ncrit: float = 9.0,
) -> dict:
    """Run one ladder level. Returns a dict with status and, if converged, coefficients."""
    cfg = LEVELS[level]
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    for f in (POLAR, DUMP, CPWR):
        (work / f).unlink(missing_ok=True)
    local = work / "coords.dat"
    if Path(coords_path).resolve() != local.resolve():
        shutil.copyfile(coords_path, local)
    alphas = alpha_schedule(alpha, cfg["continuation"])
    script = build_script(local.name, re, alphas, cfg["n_iter"], cfg["npanel"], ncrit)
    (work / "script.in").write_text(script)
    binary = xfoil_bin()
    if not binary:
        return {"status": "not_converged", "level": level, "signature": "xfoil_missing"}
    try:
        proc = _exec([binary], script, work, timeout)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "level": level, "signature": f"timeout@L{level}"}
    (work / STDOUT).write_text((proc.stdout or "") + (proc.stderr or ""))
    polar = work / POLAR
    text = polar.read_text() if polar.exists() else ""
    rows = parse_polar(text)
    hit = [r for r in rows if abs(r["alpha"] - alpha) < 1e-3]
    if not hit:
        raw = [r for r in parse_polar(text, finite_only=False) if abs(r["alpha"] - alpha) < 1e-3]
        if raw:
            sig = f"nonfinite_coeffs@L{level}"
        elif proc.returncode:
            sig = f"crash_rc{proc.returncode}@L{level}"
        else:
            sig = f"not_converged@L{level}"
        return {"status": "not_converged", "level": level, "signature": sig}
    out = {"status": "converged", "level": level, **hit[-1]}
    dump = work / DUMP
    try:
        out["dump"] = parse_dump(dump.read_text()) if dump.exists() else None
    except NonFiniteDump:
        return {"status": "not_converged", "level": level, "signature": f"nonfinite_cf@L{level}"}
    return out


def evaluate(
    params: WingParams, spec: DesignSpec, coords_path: str | Path, run_dir: str | Path, level: int
) -> CFDResult:
    t0 = time.perf_counter()
    work = Path(run_dir) / params.cid / f"xfoil_L{level}"
    r = run_xfoil(coords_path, spec.reynolds, params.alpha_deg, level, work, ncrit=spec.ncrit)
    artifacts = {
        k: str(work / f) for k, f in (("polar", POLAR), ("bl_dump", DUMP), ("cp", CPWR)) if (work / f).exists()
    }
    if r["status"] != "converged":
        return CFDResult(
            cid=params.cid,
            fidelity="xfoil",
            status=r["status"],
            solver_level=level,
            failure_signature=r["signature"],
            log_path=str(work / STDOUT),
            artifacts=artifacts,
            wall_s=time.perf_counter() - t0,
        )
    bl = summarize_bl(r["dump"], r["cl"], r) if r.get("dump") is not None else None
    return CFDResult(
        cid=params.cid,
        fidelity="xfoil",
        status="converged",
        cl=-r["cl"],  # race-car convention
        cd=r["cd"],
        cm=-r["cm"],
        solver_level=level,
        bl=bl,
        log_path=str(work / STDOUT),
        artifacts=artifacts,
        wall_s=time.perf_counter() - t0,
    )


def next_level(tried: list[int]) -> int | None:
    for lvl in range(MAX_LEVEL + 1):
        if lvl not in tried:
            return lvl
    return None
