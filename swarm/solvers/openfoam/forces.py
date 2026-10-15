"""Forces, surface Cp / Cf and y+ from the fields simpleFoam writes (no function objects).

The Debian OpenFOAM v1912 build aborts any run that loads a function object ("sha1" IOstream error), so the
forces are integrated here from the near-wall cells, whose index is the wall face index (the O-grid's first
layer, `swarm.solvers.openfoam.mesh`):
- pressure: the wall-adjacent cell's p (zeroGradient at the wall, first cell ~1e-5 c thick), force p * A * n_in;
- shear: tau_w = nu * U_t / d (no-slip wall, first cell inside the viscous sublayer, y+ ~ 1; nut = 0 there),
  force tau_w * A along the cell's tangential velocity.
Non-dimensional (rho 1, |U| 1, chord 1): coefficients are force / (0.5 * span). The section is upright;
race-car Cl is minus the upright Cl, as at T0/T1.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from swarm.solvers.openfoam.mesh import load_wall

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|nan|-?inf"


def read_internal(path: str | Path, n: int) -> np.ndarray:
    """internalField of an ascii OpenFOAM field: shape (n,) for scalars, (n, 3) for vectors."""
    text = Path(path).read_text()
    m = re.search(r"internalField\s+(uniform|nonuniform)", text)
    if m is None:
        raise ValueError(f"no internalField in {path}")
    rest = text[m.end() :]
    if m[1] == "uniform":
        vals = [float(v) for v in re.findall(_NUM, rest.split(";", 1)[0])]
        return np.tile(vals, (n, 1)) if len(vals) > 1 else np.full(n, vals[0])
    kind, rest = rest.split(None, 1)  # List<scalar> / List<vector>
    count, rest = rest.split(None, 1)
    body = rest[rest.index("(") + 1 :]
    width = 3 if "vector" in kind else 1
    vals = np.array(re.findall(_NUM, body[: _matching_close(body)]), dtype=float)
    if len(vals) < int(count) * width:
        raise ValueError(f"{path}: {len(vals)} values for {count} x {width}")
    vals = vals[: int(count) * width]
    return vals.reshape(int(count), 3) if width == 3 else vals


def _matching_close(body: str) -> int:
    depth = 0
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return i
            depth -= 1
    return len(body)


def time_dirs(case_dir: str | Path) -> list[tuple[int, Path]]:
    out = []
    for d in Path(case_dir).iterdir():
        if d.is_dir() and re.fullmatch(r"\d+", d.name) and d.name != "0" and (d / "U").exists():
            out.append((int(d.name), d))
    return sorted(out)


def coefficients(case_dir: str | Path, time_dir: str | Path, alpha_deg: float, reynolds: float, span: float) -> dict:
    """Upright-frame Cl, Cd, Cm (about x/c 0.25) and per-wall-face Cp, Cf, y+ for one written time."""
    w = load_wall(case_dir)
    n = len(w["length"])
    p = read_internal(Path(time_dir) / "p", n * 0 + _ncells(case_dir))[:n]
    u = read_internal(Path(time_dir) / "U", _ncells(case_dir))[:n, :2]
    nu = 1.0 / reynolds
    area = w["length"] * span
    f_p = (p * area)[:, None] * w["n_in"]
    u_t = u - (u * w["n_in"]).sum(axis=1, keepdims=True) * w["n_in"]  # tangential part of the cell velocity
    tau = nu * u_t / w["dist"][:, None]  # wall shear stress vector (kinematic), along the near-wall flow
    f_v = tau * area[:, None]
    f = f_p.sum(axis=0) + f_v.sum(axis=0)
    a = math.radians(alpha_deg)
    lift_dir, drag_dir = np.array([-math.sin(a), math.cos(a)]), np.array([math.cos(a), math.sin(a)])
    q = 0.5 * span
    r = w["centre"] - np.array([0.25, 0.0])
    ft = f_p + f_v
    torque = float((r[:, 0] * ft[:, 1] - r[:, 1] * ft[:, 0]).sum())  # z-moment, nose-up positive
    tau_mag = np.linalg.norm(tau, axis=1)
    cf_signed = 2.0 * (tau * w["t"]).sum(axis=1)  # along the loop direction
    return {
        "cl": float(f @ lift_dir / q),
        "cd": float(f @ drag_dir / q),
        "cm": float(torque / (q * 1.0)),
        "cp": 2.0 * p,
        "cf_loop": cf_signed,
        "yplus": np.sqrt(tau_mag) * w["dist"] / nu,
        "x": w["centre"][:, 0],
        "y": w["centre"][:, 1],
        "tx": w["t"][:, 0],
        "base": w["base"] if "base" in w else w["centre"][:, 0] > w["centre"][:, 0].max() - 1e-4,
    }


def span_of(case_dir: str | Path) -> float:
    """z thickness of the slab, from the Aref the case was written with (system/controlDict note)."""
    m = re.search(r"//\s*span\s+([\d.eE+-]+)", (Path(case_dir) / "system" / "controlDict").read_text())
    if m is None:
        raise ValueError("controlDict has no span note")
    return float(m[1])


def _ncells(case_dir: str | Path) -> int:
    owner = (Path(case_dir) / "constant" / "polyMesh" / "owner").read_text()
    m = re.search(r"nCells:\s*(\d+)", owner)
    if m is None:
        raise ValueError("owner file has no nCells note")
    return int(m[1])


def history(case_dir: str | Path, alpha_deg: float, reynolds: float, span: float) -> list[tuple[int, float, float]]:
    """(iteration, Cl, Cd) for every written time (upright frame)."""
    out = []
    for it, d in time_dirs(case_dir):
        c = coefficients(case_dir, d, alpha_deg, reynolds, span)
        out.append((it, c["cl"], c["cd"]))
    return out


def surface(c: dict, upright_cl: float) -> dict:
    """Surface data in the swarm.critic.surface format: {"suction": {x, cp, cf, h}, "pressure": {...}, "source"}.

    Splits the closed loop at the leading edge (min x) and at the blunt base (`mesh.wall_geometry` "base"),
    each side ordered LE -> TE. Cf is signed positive for flow from the leading edge towards the trailing edge."""
    x, y = c["x"], c["y"]
    n = len(x)
    ile = int(np.argmin(x))
    on_base = np.asarray(c["base"], dtype=bool)
    order = np.roll(np.arange(n), -ile)  # LE first, then around the loop
    keep = order[~on_base[order]]
    # the loop from the LE runs along one side to the base, then back along the other side
    gaps = np.where(np.diff(np.flatnonzero(~on_base[order])) > 1)[0]
    split = gaps[0] + 1 if len(gaps) else len(keep) // 2
    a, b = keep[:split], keep[split:][::-1]
    a, b = a[np.argsort(x[a])], b[np.argsort(x[b])]
    upper, lower = (a, b) if y[a].mean() > y[b].mean() else (b, a)

    def side(ii: np.ndarray) -> dict:
        sign = np.sign(c["tx"][ii])  # +1 where the loop runs towards the TE
        return {"x": x[ii], "cp": c["cp"][ii], "cf": sign * c["cf_loop"][ii], "h": np.full(len(ii), np.nan)}

    up, lo = side(upper), side(lower)
    suction, pressure = (up, lo) if upright_cl >= 0 else (lo, up)
    return {"suction": suction, "pressure": pressure, "source": "OpenFOAM simpleFoam (wall-adjacent cells)"}
