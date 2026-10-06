"""Gated XFoil sweep at the hard preset's Re: which designs pass the full gate, and where.

    uv run python scripts/gated_sweep.py run runs_gated gated.json     # XFoil, a few minutes on 4 cores
    uv run python scripts/gated_sweep.py analyze gated.json
    uv run python scripts/gated_sweep.py propose gated.json

Grid: camber 0.06-0.09 step 0.005, position 0.25-0.55 step 0.05, thickness
{0.0955, 0.11, 0.12, 0.135, 0.15}, alpha 4-14 step 0.25 (alpha+1 and +2 are on the grid, so
designs up to alpha 12 can be gated; with 4-10 and 4-12 the best gated designs sat on the alpha 8
and alpha 10 edges).
One XFoil session per geometry: warm up from 0 deg in 0.5 deg steps, then step alpha through
the grid with a BL dump after every point (continuation; the wrapper's L2 level does the same
from 0 deg). An alpha that does not converge in continuation is re-solved cold through the
wrapper's ladder (L0..L3).

Gate per point (alpha = a): converged at a, a+1, a+2; no TE separation at any of the three
(Cf < 0 on the suction side persisting to the TE, the wrapper's definition); stall margin =
min secant of |Cl| over a..a+2 >= stall_min_dcl_dalpha (0.05/deg). The pipeline itself does not
fail a design for separation at a+1/a+2 (it only records it), so the analysis counts both.
Geometry: every point also goes through `build()` (HARD_SPEC's rulebook); violators never pass.
Analysis (`analyze`, `propose`) keeps only sections at or above the rulebook's thickness floor
(FSAE 2027 T.7.1.4: 5 mm leading-edge radius, t >= 0.123 on the 300 mm chord) and accepts several
sweep files, comma-separated (the session-7 grid plus the session-12 FSAE thickness levels):

    uv run python scripts/gated_sweep.py run runs_fsae gated_fsae.json 0.125,0.13,0.14,0.145
    uv run python scripts/gated_sweep.py propose gated.json,gated_fsae.json
"""

from __future__ import annotations

import itertools
import json
import math
import subprocess
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from swarm.cad.build import build, main_section, write_coords
from swarm.cad.regulations import min_thickness_for_le_radius
from swarm.critic.numeric import VALIDATION
from swarm.run import HARD_SPEC
from swarm.solvers import xfoil
from swarm.state import WingParams

CAMBER = tuple(round(x, 3) for x in np.arange(0.06, 0.0901, 0.005))
POS = tuple(round(x, 2) for x in np.arange(0.25, 0.5501, 0.05))
THICK = (0.0955, 0.11, 0.12, 0.135, 0.15)
ALPHAS = tuple(round(x, 2) for x in np.arange(4.0, 14.001, 0.25))
WARMUP = tuple(round(x, 1) for x in np.arange(0.0, 4.0, 0.5))
N_ITER, NPANEL = 300, 160  # the wrapper's continuation level (L2)
T_FLOOR = min_thickness_for_le_radius(HARD_SPEC.car.chord_mm, HARD_SPEC.rulebook)


def _script(coords: str) -> str:
    s = ["PLOP", "G", "", f"LOAD {coords}", "PPAR", f"N {NPANEL}", "", "", "OPER"]
    s += [
        f"VISC {HARD_SPEC.reynolds:.0f}",
        "VPAR",
        f"N {HARD_SPEC.ncrit:g}",
        "",
        f"ITER {N_ITER}",
        "PACC",
        "polar.txt",
        "",
    ]
    s += [f"ALFA {a:.3f}" for a in WARMUP]
    for i, a in enumerate(ALPHAS):
        s += [f"ALFA {a:.3f}", f"DUMP d{i}.txt"]
    return "\n".join(s + ["PACC", "", "QUIT", ""])


def _point(m, p, t, a, cl, cd, dump, source) -> dict:
    bl = xfoil.summarize_bl(dump, cl, {}) if dump is not None else None
    return dict(m=m, p=p, t=t, a=a, status="ok", cl=cl, cd=cd, sep=bl.te_separation_xc if bl else None, source=source)


def _geometry(job) -> list[dict]:
    work, m, p, t = job
    wp = WingParams(main_camber=m, main_camber_pos=p, main_thickness=t, alpha_deg=ALPHAS[0])
    d = Path(work) / wp.cid
    d.mkdir(parents=True, exist_ok=True)
    coords = write_coords(main_section(wp), d / "coords.dat", wp.cid)
    try:
        proc = xfoil._exec([xfoil.xfoil_bin()], _script(coords.name), d, timeout=300)
        (d / "xfoil.log").write_text(proc.stdout or "")
    except subprocess.TimeoutExpired:
        pass
    polar = d / "polar.txt"
    rows = {round(r["alpha"], 2): r for r in xfoil.parse_polar(polar.read_text() if polar.exists() else "")}
    out = []
    for i, a in enumerate(ALPHAS):
        r = rows.get(a)
        dump = None
        if r is not None and (d / f"d{i}.txt").exists():
            try:
                dump = xfoil.parse_dump((d / f"d{i}.txt").read_text())
            except xfoil.NonFiniteDump:
                r = None
        if r is not None and dump is not None:
            out.append(_point(m, p, t, a, r["cl"], r["cd"], dump, "continuation"))
            continue
        # cold re-solve through the wrapper's ladder, exactly as the pipeline would
        row = dict(m=m, p=p, t=t, a=a, status="fail", source="ladder")
        for lvl in range(xfoil.MAX_LEVEL + 1):
            rr = xfoil.run_xfoil(coords, HARD_SPEC.reynolds, a, lvl, d / f"a{a:+.2f}_L{lvl}", ncrit=HARD_SPEC.ncrit)
            if rr["status"] == "converged" and rr.get("dump") is not None:
                row = _point(m, p, t, a, rr["cl"], rr["cd"], rr["dump"], f"ladder_L{lvl}")
                break
        out.append(row)
    for r in out:  # geometry and rulebook checks (HARD_SPEC.rulebook) at the point's alpha
        g = build(WingParams(main_camber=m, main_camber_pos=p, main_thickness=t, alpha_deg=r["a"]), HARD_SPEC, work)
        r["violations"] = g.violations
    return out


def run(work: str, out: str, thick: tuple[float, ...] = THICK) -> None:
    jobs = [(work, m, p, t) for m, p, t in itertools.product(CAMBER, POS, thick)]
    with Pool(4) as pool:
        rows = [r for rs in pool.map(_geometry, jobs, chunksize=2) for r in rs]
    Path(out).write_text(json.dumps(rows))
    n_fail = sum(r["status"] != "ok" for r in rows)
    n_lad = sum(r["source"].startswith("ladder") and r["status"] == "ok" for r in rows)
    print(f"{len(jobs)} geometries, {len(rows)} points: {n_fail} failed, {n_lad} recovered by the cold ladder")


def gate(rows: list[dict]) -> list[dict]:
    """Each point with margin / separation facts and `passes` (the full gate, user definition)."""
    by: dict[tuple, dict] = defaultdict(dict)
    for r in rows:
        by[(r["m"], r["p"], r["t"])][r["a"]] = r
    out = []
    for pts in by.values():
        for a, r in pts.items():
            trio = [pts.get(round(a + d, 2)) for d in (0.0, *VALIDATION.stall_probe_deg)]
            g = dict(r, margin=None, sep_probe=None, passes=False, passes_pipeline=False)
            if all(x is not None and x["status"] == "ok" for x in trio):
                cls = [abs(x["cl"]) for x in trio]
                als = [x["a"] for x in trio]
                g["margin"] = min((c1 - c0) / (a1 - a0) for c0, c1, a0, a1 in zip(cls, cls[1:], als, als[1:]))  # noqa: B905
                g["sep_probe"] = any(x["sep"] is not None for x in trio[1:])
                ok = r["sep"] is None and g["margin"] >= VALIDATION.stall_min_dcl_dalpha and not r["violations"]
                g["passes_pipeline"] = ok  # the pipeline's gate: separation at the probes is only logged
                g["passes"] = ok and not g["sep_probe"]
            out.append(g)
    return out


def in_box(r: dict, target: float, tol: float, cd_max: float) -> bool:
    return abs(abs(r["cl"]) - abs(target)) <= tol and r["cd"] <= cd_max


def load(paths: str) -> list[dict]:
    """Sweep rows from comma-separated files, legal sections only (t >= the rulebook's floor)."""
    rows = [r for p in paths.split(",") for r in json.loads(Path(p).read_text())]
    return [r for r in rows if r["t"] >= T_FLOOR]


def analyze(path: str) -> None:
    g = gate(load(path))
    ok = [r for r in g if r["status"] == "ok"]
    gated = [r for r in g if r["passes"]]
    print(
        f"{len(g)} points, {len(ok)} converged, {len(gated)} pass the full gate "
        f"({sum(r['passes_pipeline'] for r in g)} pass the pipeline's gate)"
    )
    top = max(gated, key=lambda r: abs(r["cl"]))
    print(
        f"gated Cl_max = {abs(top['cl']):.4f} at m {top['m']} p {top['p']} t {top['t']} alpha {top['a']} "
        f"(Cd {top['cd']:.5f}, margin {top['margin']:.3f})"
    )
    cl = np.array([abs(r["cl"]) for r in gated])
    print(
        f"gated |Cl| range {cl.min():.3f}-{cl.max():.3f}; "
        f"quantiles 50/90/99%: {np.quantile(cl, [0.5, 0.9, 0.99]).round(3)}"
    )
    cur = [r for r in gated if in_box(r, HARD_SPEC.target_cl, HARD_SPEC.cl_tol, HARD_SPEC.cd_max)]
    print(f"current box (Cl {HARD_SPEC.target_cl} ± {HARD_SPEC.cl_tol}, Cd <= {HARD_SPEC.cd_max}): {len(cur)} pass")
    for r in sorted(cur, key=lambda r: -abs(r["cl"])):
        print(
            f"   m {r['m']} p {r['p']} t {r['t']} a {r['a']}: Cl {abs(r['cl']):.4f} Cd {r['cd']:.5f} "
            f"margin {r['margin']:.3f}"
        )
    print("\ngated Cl_max by camber (bound 0.09):")
    for m in CAMBER:
        rs = [r for r in gated if r["m"] == m]
        if rs:
            b = max(rs, key=lambda r: abs(r["cl"]))
            print(f"   m {m}: {abs(b['cl']):.4f} (p {b['p']} t {b['t']} a {b['a']})")


def interior(r: dict, t_low: float) -> bool:
    """Away from the bounds that bind here: camber < 0.09 (WingParams) and thickness above `t_low`,
    the lowest legal grid level (the one at the rulebook's leading-edge floor)."""
    return r["m"] < max(CAMBER) - 1e-9 and r["t"] > t_low + 1e-9


def propose(path: str, min_points: int = 10, tol: float = HARD_SPEC.cl_tol) -> None:
    """Highest |Cl| target whose ±tol band holds >= min_points interior passing points; Cd cap
    = worst Cd among them + 5%, rounded up to 0.0005 (session 3's convention)."""
    gated = [r for r in gate(load(path)) if r["passes"]]
    t_low = min(r["t"] for r in gated)
    top = max(abs(r["cl"]) for r in gated)
    for k in range(int(top * 100), 0, -1):
        t = k / 100
        band = [r for r in gated if interior(r, t_low) and abs(abs(r["cl"]) - t) <= tol]
        if len(band) >= min_points:
            break
    cap = math.ceil(max(r["cd"] for r in band) * 1.05 / 0.0005) * 0.0005
    box = [r for r in gated if in_box(r, -t, tol, cap)]
    print(f"proposed target Cl -{t:.2f} ± {tol}, Cd <= {cap:.4f} ({t / top:.1%} of gated Cl_max {top:.4f})")
    print(f"  {len(box)} passing grid points in the box, {sum(interior(r, t_low) for r in box)} interior:")
    for r in sorted(box, key=lambda r: (r["m"], r["p"], r["t"], r["a"])):
        tag = "" if interior(r, t_low) else "  (on a bound)"
        print(
            f"   m {r['m']} p {r['p']} t {r['t']} a {r['a']}: Cl {abs(r['cl']):.4f} Cd {r['cd']:.5f} "
            f"margin {r['margin']:.3f}{tag}"
        )
    near = [r for r in gated if abs(abs(r["cl"]) - t) <= tol]
    print(
        f"  in the Cl band regardless of Cd: {len(near)}; all passing points with |Cl| >= {t - tol:.2f}: "
        f"{sum(abs(r['cl']) >= t - tol for r in gated)}"
    )


if __name__ == "__main__":
    if sys.argv[1] == "run":  # optional 4th argument: thickness levels, e.g. 0.125,0.13,0.14
        run(sys.argv[2], sys.argv[3], tuple(float(x) for x in sys.argv[4].split(",")) if len(sys.argv) > 4 else THICK)
    elif sys.argv[1] == "propose":
        propose(sys.argv[2])
    else:
        analyze(sys.argv[2])
