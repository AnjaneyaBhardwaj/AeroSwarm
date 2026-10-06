"""Deterministic geometry compiler (BLUEPRINT §2, layer 3).

Milestone 1 builds 2D sections only. CadQuery/STEP/STL export arrives with
the OpenFOAM milestone; the checks below are the 2D subset of
`export_and_validate`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from swarm.cad.regulations import check_regulations
from swarm.state import DesignSpec, GeometryArtifact, ReferenceCar, WingParams

# 0.7% c ≈ 2 mm on a 300 mm chord: a 1 mm edge radius (not sharp: FSAE T.7.1.5; FS2026 T2.4.1).
DEFAULT_TE_THICK = 0.007
TE_MESH_FLOOR = 0.002  # fraction of chord; thinner TEs won't mesh at T2
MIN_GAP = 0.003  # fraction of chord, between elements


def naca4(m: float, p: float, t: float, n: int = 161, te_thick: float = DEFAULT_TE_THICK):
    """NACA 4-digit section, unit chord, blunt TE, cosine spacing.

    Returns (2n-1, 2) points ordered TE → upper → LE → lower → TE (Selig).
    """
    beta = np.linspace(0, np.pi, n)
    x = 0.5 * (1 - np.cos(beta))
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1015 * x**4)
    yt = yt + te_thick / 2 * x  # blunt TE → meshable
    if m > 0:
        yc = np.where(x < p, m / p**2 * (2 * p * x - x**2), m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x**2))
        dyc = np.where(x < p, 2 * m / p**2 * (p - x), 2 * m / (1 - p) ** 2 * (p - x))
    else:
        yc = np.zeros_like(x)
        dyc = np.zeros_like(x)
    th = np.arctan(dyc)
    xu, yu = x - yt * np.sin(th), yc + yt * np.cos(th)
    xl, yl = x + yt * np.sin(th), yc - yt * np.cos(th)
    return np.vstack([np.c_[xu[::-1], yu[::-1]], np.c_[xl[1:], yl[1:]]])


def main_section(params: WingParams, n: int = 161) -> np.ndarray:
    """Upright main-element section at unit chord, unrotated (solver frame)."""
    return naca4(params.main_camber, params.main_camber_pos, params.main_thickness, n=n)


def placed(params: WingParams, inverted: bool = True) -> np.ndarray:
    """Unit-chord section in race-car orientation: inverted, TE rotated up by alpha."""
    xy = main_section(params).copy()
    if inverted:
        xy[:, 1] *= -1
    a = np.deg2rad(params.alpha_deg)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    return xy @ rot.T


def placed_mm(params: WingParams, car: ReferenceCar) -> dict[str, np.ndarray]:
    """Element outlines in the car frame (mm): scaled by chord, LE at the mount point."""
    main_c = 1.0 - params.flap_chord_ratio
    pts = placed(params) * car.chord_mm * main_c
    pts = pts + np.array([car.wing_mount_x, car.wing_mount_z])
    return {"main": pts}


def write_coords(coords: np.ndarray, path: Path, name: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [name] + [f"{x: .7f} {y: .7f}" for x, y in coords]
    path.write_text("\n".join(lines) + "\n")
    return path


def _polygon_area(xy: np.ndarray) -> float:
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _segments_intersect(xy: np.ndarray) -> bool:
    """True if any two non-adjacent edges of the closed polygon cross."""
    pts = np.vstack([xy, xy[:1]])
    a, b = pts[:-1], pts[1:]
    n = len(a)

    def orient(p, q, r):
        return np.sign(
            (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
        )

    for i in range(n):
        j = np.arange(i + 2, n)
        if i == 0:
            j = j[j != n - 1]  # first and last edges share a vertex
        if not len(j):
            continue
        o1 = orient(a[i], b[i], a[j])
        o2 = orient(a[i], b[i], b[j])
        o3 = orient(a[j], b[j], a[i])
        o4 = orient(a[j], b[j], b[i])
        if np.any((o1 * o2 < 0) & (o3 * o4 < 0)):
            return True
    return False


def validate_section(coords: np.ndarray, te_floor: float = TE_MESH_FLOOR) -> tuple[dict[str, bool], list[str], float]:
    """2D checks. Returns (checks, violations, te_thickness)."""
    n = (len(coords) + 1) // 2
    upper = coords[:n][::-1]  # LE → TE
    lower = coords[n - 1 :]  # LE → TE
    te = float(np.hypot(*(coords[0] - coords[-1])))
    common = np.linspace(0.0, 1.0, 201)
    yu = np.interp(common, upper[:, 0], upper[:, 1])
    yl = np.interp(common, lower[:, 0], lower[:, 1])
    thick = yu - yl
    area = abs(_polygon_area(coords))
    checks = {
        "finite": bool(np.all(np.isfinite(coords))),
        "positive_area": area > 1e-4,
        "no_self_intersection": not _segments_intersect(coords),
        "positive_thickness": bool(np.all(thick[1:-1] > 0)),
        "te_above_mesh_floor": te >= te_floor,
    }
    messages = {
        "finite": "geometry: non-finite coordinates",
        "positive_area": f"geometry: section area {area:.2e} is not positive",
        "no_self_intersection": "geometry: section outline self-intersects",
        "positive_thickness": "geometry: upper and lower surfaces cross (negative thickness)",
        "te_above_mesh_floor": f"geometry: TE thickness {te:.4f} c below mesh floor {te_floor} c",
    }
    return checks, [messages[k] for k, ok in checks.items() if not ok], te


def build(params: WingParams, spec: DesignSpec, out_dir: str | Path) -> GeometryArtifact:
    """Build and validate the section. Violations go to `pending_violation`."""
    out_dir = Path(out_dir)
    violations: list[str] = []
    if spec.component == "wing_1el" and params.flap_chord_ratio > 0:
        violations.append("component wing_1el: flap_chord_ratio must be 0 (XFoil is single-element)")
    coords = main_section(params)
    checks, geo_v, te = validate_section(coords)
    violations += geo_v
    if spec.rulebook != "none":
        reg = check_regulations(placed_mm(params, spec.car), params, spec.car, spec.rulebook)
        checks["regulations"] = not reg
        violations += reg
    path = write_coords(coords, out_dir / params.cid / "coords.dat", f"aeroswarm-{params.cid}")
    return GeometryArtifact(
        cid=params.cid,
        coords_path=str(path),
        checks=checks,
        te_thickness=te,
        violations=violations,
    )
