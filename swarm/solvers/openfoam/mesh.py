"""Structured 2D O-grid around a single-element section, written straight to OpenFOAM's polyMesh format.

BLUEPRINT §4 suggests snappyHexMesh + extrudeMesh. For one closed section a structured O-grid is more robust,
deterministic and testable without OpenFOAM: the surface (with its blunt trailing-edge base) is resampled with
clustering at the leading and trailing edges, then layers are marched outward. Each layer moves along the
smoothed normals of the previous one by a geometrically growing step (first step `first_cell`, chosen for
y+ ~ 1), and the far field is a circle of radius `farfield` chords. One cell thick in z (front and back are
`empty` patches). Units: chord 1.

Patches: `airfoil` (wall), `farfield`, `frontAndBack` (empty).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class MeshSpec:
    n_surface: int = 240  # cells around the section (both surfaces)
    n_base: int = 6  # cells across the blunt trailing-edge base
    first_cell: float = 2e-5  # wall-normal size of the first cell (chord units)
    growth: float = 1.12  # geometric growth of the wall-normal step
    max_step: float = 1.0  # cap on the wall-normal step (chord units)
    farfield: float = 30.0  # far-field radius (chords), measured from mid-chord
    smoothing: int = 12  # normal-smoothing passes per layer (more far from the wall)
    span: float = 0.1  # z thickness of the one-cell slab (chord units)


def _resample(xy: np.ndarray, n: int) -> np.ndarray:
    """n+1 points along an open polyline, clustered at both ends (cosine in arc length)."""
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    t = 0.5 * (1 - np.cos(np.linspace(0, np.pi, n + 1))) * s[-1]
    return np.c_[np.interp(t, s, xy[:, 0]), np.interp(t, s, xy[:, 1])]


def surface_loop(coords: np.ndarray, spec: MeshSpec) -> np.ndarray:
    """Closed loop (counter-clockwise, no repeated point): TE(lower) -> lower -> LE -> upper -> TE(upper) -> base.

    `coords`: Selig order (TE upper -> LE -> TE lower), as `swarm.cad.build.naca4`.
    """
    ile = int(np.argmin(coords[:, 0]))
    upper = coords[: ile + 1][::-1]  # LE -> TE upper
    lower = coords[ile:]  # LE -> TE lower
    n_side = spec.n_surface // 2
    lo = _resample(lower[::-1], n_side)  # TE lower -> LE
    up = _resample(upper, n_side)  # LE -> TE upper
    base = np.linspace(up[-1], lo[0], spec.n_base + 1)  # TE upper -> TE lower
    loop = np.vstack([lo[:-1], up[:-1], base[:-1]])
    # counter-clockwise (positive signed area) so the outward normal is (dy, -dx) rotated correctly
    area = 0.5 * np.sum(loop[:, 0] * np.roll(loop[:, 1], -1) - np.roll(loop[:, 0], -1) * loop[:, 1])
    return loop if area > 0 else loop[::-1]


def _normals(loop: np.ndarray) -> np.ndarray:
    """Outward unit normals of a counter-clockwise closed loop (central differences)."""
    t = np.roll(loop, -1, axis=0) - np.roll(loop, 1, axis=0)
    n = np.c_[t[:, 1], -t[:, 0]]
    return n / np.linalg.norm(n, axis=1, keepdims=True)


def _smooth(v: np.ndarray, passes: int) -> np.ndarray:
    for _ in range(passes):
        v = 0.5 * v + 0.25 * (np.roll(v, 1, axis=0) + np.roll(v, -1, axis=0))
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _inverted(prev: np.ndarray, nxt: np.ndarray) -> int:
    """Cells between two layers whose orientation differs from the majority (folded)."""
    a, b, c, d = prev, np.roll(prev, -1, axis=0), np.roll(nxt, -1, axis=0), nxt
    q = np.stack([a, b, c, d], axis=1)
    x, y = q[..., 0], q[..., 1]
    area = 0.5 * (x * np.roll(y, -1, axis=1) - np.roll(x, -1, axis=1) * y).sum(axis=1)
    sign = np.sign(np.median(area))
    return int(np.sum(np.sign(area) != sign))


def _interior_point(loop: np.ndarray) -> np.ndarray:
    """A point inside the section: mid-chord, halfway between the two surfaces."""
    x = loop[:, 0]
    xm = 0.5 * (x.min() + x.max())
    near = loop[np.abs(x - xm) < 0.05 * (x.max() - x.min())]
    return np.array([xm, 0.5 * (near[:, 1].min() + near[:, 1].max())])


def _star_shaped(layer: np.ndarray, centre: np.ndarray) -> bool:
    """Angles about `centre` increase monotonically around the loop (one full turn)."""
    ang = np.unwrap(np.arctan2(*(layer - centre).T[::-1]))
    step = np.diff(np.r_[ang, ang[0] + 2 * np.pi])
    return bool(np.all(step > 0))


def o_grid(coords: np.ndarray, spec: MeshSpec | None = None) -> np.ndarray:
    """Grid points, shape (n_layers + 1, n_around, 2): layer 0 is the surface, the last layer the far field.

    Near the wall each layer marches along the smoothed normals of the previous one (orthogonal cells for the
    boundary layer); a layer that would fold a cell is re-marched with stronger smoothing. Once a layer is
    star-shaped about a point inside the section, the directions blend within one chord into pure rays from that
    point; with the same step for every point, rays cannot cross, so the outer grid cannot fold. The far field is
    the last layer projected onto a circle."""
    spec = spec or MeshSpec()
    loop = surface_loop(coords, spec)
    centre = _interior_point(loop)
    layers = [loop]
    step, dist, star_at = spec.first_cell, 0.0, None
    while True:
        prev = layers[-1]
        if star_at is None and dist > 0.05 and _star_shaped(prev, centre):
            star_at = dist
        w = 0.0 if star_at is None else min(1.0, (dist - star_at) / 1.0)
        radial = prev - centre
        radial /= np.linalg.norm(radial, axis=1, keepdims=True)
        for attempt in range(12):
            # little smoothing in the boundary layer (orthogonal cells), much more beyond it (concave parts)
            n = _smooth(_normals(prev), (spec.smoothing + int(200 * min(1.0, dist))) * 2**attempt)
            d = (1 - w) * n + w * radial
            d /= np.linalg.norm(d, axis=1, keepdims=True)
            nxt = prev + step * d
            # Laplacian smoothing of the new points beyond the boundary layer (evens out the spacing over concave
            # parts), stronger on each retry
            lam = min(0.5, 0.05 * attempt + (0.1 if dist > 0.02 else 0.0))
            if lam:
                for _ in range(2 + 4 * attempt):
                    nxt = nxt + lam * (0.5 * (np.roll(nxt, 1, axis=0) + np.roll(nxt, -1, axis=0)) - nxt)
            if not _inverted(prev, nxt):
                break
        else:
            raise ValueError(f"O-grid folds at distance {dist:.3g} c and smoothing could not repair it")
        dist += step
        r = np.linalg.norm(nxt - centre, axis=1)
        if r.min() >= spec.farfield:
            layers.append(centre + r.max() * (nxt - centre) / r[:, None])  # round off: a circle through the far point
            break
        layers.append(nxt)
        step = min(step * spec.growth, spec.max_step)
    return np.array(layers)


def quality(grid: np.ndarray) -> dict[str, float]:
    """Max non-orthogonality (deg) over internal faces and the number of folded cells, computed in 2D."""
    a, b = grid[:-1], np.roll(grid[:-1], -1, axis=1)
    c, d = np.roll(grid[1:], -1, axis=1), grid[1:]
    cent = 0.25 * (a + b + c + d)
    worst = 0.0
    # faces along j (between layers): edge d -> c of cell (j, i) shared with cell (j + 1, i)
    e = c[:-1] - d[:-1]
    nrm = np.stack([e[..., 1], -e[..., 0]], axis=-1)
    v = cent[1:] - cent[:-1]
    cosang = np.abs((nrm * v).sum(-1)) / (np.linalg.norm(nrm, axis=-1) * np.linalg.norm(v, axis=-1))
    worst = max(worst, float(np.degrees(np.arccos(np.clip(cosang.min(), -1, 1)))))
    # faces along i: edge b -> c of cell (j, i) shared with cell (j, i + 1)
    e = c - b
    nrm = np.stack([e[..., 1], -e[..., 0]], axis=-1)
    v = np.roll(cent, -1, axis=1) - cent
    cosang = np.abs((nrm * v).sum(-1)) / (np.linalg.norm(nrm, axis=-1) * np.linalg.norm(v, axis=-1))
    worst = max(worst, float(np.degrees(np.arccos(np.clip(cosang.min(), -1, 1)))))
    folded = sum(_inverted(grid[j], grid[j + 1]) for j in range(len(grid) - 1))
    return {"max_non_ortho": worst, "folded": folded}


def _header(cls: str, obj: str, note: str = "") -> str:
    return (
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
        f"    class       {cls};\n"
        + (f'    note        "{note}";\n' if note else "")
        + '    location    "constant/polyMesh";\n'
        f"    object      {obj};\n}}\n\n"
    )


def write_polymesh(grid: np.ndarray, case_dir: str | Path, span: float) -> dict:
    """Write constant/polyMesh for the one-cell-thick slab; returns {cells, faces, points}."""
    nj1, ni, _ = grid.shape
    nj = nj1 - 1
    pts2 = grid.reshape(-1, 2)  # index j*ni + i
    npl = len(pts2)
    points = np.vstack([np.c_[pts2, np.zeros(npl)], np.c_[pts2, np.full(npl, span)]])

    def p(i: int, j: int, k: int) -> int:
        return k * npl + j * ni + (i % ni)

    def c(i: int, j: int) -> int:
        return j * ni + (i % ni)

    cent = np.array([[0.25 * (grid[j, i] + grid[j, (i + 1) % ni] + grid[j + 1, i] + grid[j + 1, (i + 1) % ni])
                      for i in range(ni)] for j in range(nj)]).reshape(-1, 2)  # fmt: skip

    def oriented(face: list[int], frm: np.ndarray, to: np.ndarray) -> list[int]:
        q = points[face]
        nrm = np.cross(q[2] - q[0], q[3] - q[1])
        d = np.r_[to - frm, 0.0]
        return face if np.dot(nrm, d) > 0 else face[::-1]

    internal = []
    for j in range(nj):
        for i in range(ni):
            a = c(i, j)
            b = c(i + 1, j)  # across the i+1 grid line
            f = [p(i + 1, j, 0), p(i + 1, j + 1, 0), p(i + 1, j + 1, 1), p(i + 1, j, 1)]
            own, nb = min(a, b), max(a, b)
            internal.append((own, nb, oriented(f, cent[own], cent[nb])))
            if j + 1 < nj:
                b = c(i, j + 1)
                f = [p(i, j + 1, 0), p(i + 1, j + 1, 0), p(i + 1, j + 1, 1), p(i, j + 1, 1)]
                internal.append((a, b, oriented(f, cent[a], cent[b])))
    internal.sort(key=lambda t: (t[0], t[1]))

    def outward(face: list[int], cell: int, toward: np.ndarray) -> list[int]:
        return oriented(face, cent[cell], toward)

    wall, far, fb = [], [], []
    for i in range(ni):
        f = [p(i, 0, 0), p(i + 1, 0, 0), p(i + 1, 0, 1), p(i, 0, 1)]
        wall.append((c(i, 0), outward(f, c(i, 0), 0.5 * (grid[0, i] + grid[0, (i + 1) % ni]))))
        f = [p(i, nj, 0), p(i + 1, nj, 0), p(i + 1, nj, 1), p(i, nj, 1)]
        far.append((c(i, nj - 1), outward(f, c(i, nj - 1), 0.5 * (grid[nj, i] + grid[nj, (i + 1) % ni]))))
    for j in range(nj):
        for i in range(ni):
            f0 = [p(i, j, 0), p(i + 1, j, 0), p(i + 1, j + 1, 0), p(i, j + 1, 0)]
            q = points[f0]
            if np.cross(q[2] - q[0], q[3] - q[1])[2] > 0:  # front (z = 0) faces point to -z
                f0 = f0[::-1]
            fb.append((c(i, j), f0))
            f1 = [x + npl for x in f0][::-1]  # back (z = span) faces point to +z
            fb.append((c(i, j), f1))

    faces = [f for _, _, f in internal] + [f for _, f in wall] + [f for _, f in far] + [f for _, f in fb]
    owner = [o for o, _, _ in internal] + [o for o, _ in wall] + [o for o, _ in far] + [o for o, _ in fb]
    neigh = [n for _, n, _ in internal]
    ncells = ni * nj
    d = Path(case_dir) / "constant" / "polyMesh"
    d.mkdir(parents=True, exist_ok=True)
    note = f"nPoints:{len(points)} nCells:{ncells} nFaces:{len(faces)} nInternalFaces:{len(internal)}"
    (d / "points").write_text(
        _header("vectorField", "points")
        + f"{len(points)}\n(\n"
        + "\n".join(f"({x:.10g} {y:.10g} {z:.10g})" for x, y, z in points)
        + "\n)\n"
    )
    (d / "faces").write_text(
        _header("faceList", "faces")
        + f"{len(faces)}\n(\n"
        + "\n".join("4(" + " ".join(map(str, f)) + ")" for f in faces)
        + "\n)\n"
    )
    (d / "owner").write_text(
        _header("labelList", "owner", note) + f"{len(owner)}\n(\n" + "\n".join(map(str, owner)) + "\n)\n"
    )
    (d / "neighbour").write_text(
        _header("labelList", "neighbour", note) + f"{len(neigh)}\n(\n" + "\n".join(map(str, neigh)) + "\n)\n"
    )
    n_int = len(internal)
    patches = [
        ("airfoil", "wall", len(wall), n_int),
        ("farfield", "patch", len(far), n_int + len(wall)),
        ("frontAndBack", "empty", len(fb), n_int + len(wall) + len(far)),
    ]
    body = "".join(
        f"    {name}\n    {{\n        type {typ};\n        nFaces {nf};\n        startFace {sf};\n    }}\n"
        for name, typ, nf, sf in patches
    )
    (d / "boundary").write_text(_header("polyBoundaryMesh", "boundary") + f"{len(patches)}\n(\n{body})\n")
    save_wall(grid, Path(case_dir))
    return {"cells": ncells, "faces": len(faces), "points": len(points), "n_around": ni, "n_layers": nj}


WALL_FILE = "wall_geometry.npz"


def wall_geometry(grid: np.ndarray) -> dict[str, np.ndarray]:
    """Per wall face i (surface segment i -> i+1, owner cell (i, 0)): face centre, unit normal into the body,
    unit tangent along the loop, length (chord units), owner-cell centroid and its wall distance."""
    a, b = grid[0], np.roll(grid[0], -1, axis=0)
    a1, b1 = grid[1], np.roll(grid[1], -1, axis=0)
    edge = b - a
    length = np.linalg.norm(edge, axis=1)
    t = edge / length[:, None]
    out_n = np.c_[t[:, 1], -t[:, 0]]  # loop is counter-clockwise: (ty, -tx) points into the fluid
    centre = 0.5 * (a + b)
    quad = np.stack([a, b, b1, a1], axis=1)
    x, y = quad[..., 0], quad[..., 1]
    xn, yn = np.roll(x, -1, axis=1), np.roll(y, -1, axis=1)
    cross = x * yn - xn * y
    area = 0.5 * cross.sum(axis=1)
    cell = np.c_[((x + xn) * cross).sum(axis=1), ((y + yn) * cross).sum(axis=1)] / (6 * area[:, None])
    dist = np.abs(((cell - centre) * out_n).sum(axis=1))
    # the blunt trailing-edge base: faces at the trailing edge whose tangent is across the chord (it is slanted on a
    # cambered section, so x alone does not identify it)
    x = grid[0][:, 0]
    base = (centre[:, 0] > x.min() + 0.9 * (x.max() - x.min())) & (np.abs(t[:, 0]) < 0.5)
    return {"centre": centre, "n_in": -out_n, "t": t, "length": length, "cell": cell, "dist": dist, "base": base}


def save_wall(grid: np.ndarray, case_dir: Path) -> None:
    np.savez(case_dir / WALL_FILE, **wall_geometry(grid))


def load_wall(case_dir: str | Path) -> dict[str, np.ndarray]:
    with np.load(Path(case_dir) / WALL_FILE) as z:
        return {k: z[k] for k in z.files}
