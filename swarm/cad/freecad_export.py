"""CAD files for a finished run, built in FreeCAD (headless `freecadcmd`).

Deterministic and outside the agent loop: no agent sees or drives FreeCAD. For a run directory this picks the
start design and the final one (the best passing design, else the closest candidate, as in the report), computes
their outlines at real scale, and asks FreeCAD (swarm/cad/freecad_doc.py, run in FreeCAD's own Python) to build:

- <name>.FCStd   FreeCAD document: start and final sections as faces with chord lines, plus a "Design"
                 spreadsheet of their parameters and ledger results
- <name>.step    the two section faces, for any CAD program
- <name>.dat     the final section's coordinates (Selig format, unit chord, upright: what XFoil was given)

FreeCAD's measured face area is checked against this module's own polygon area; a mismatch over AREA_TOL fails
the export instead of shipping a wrong file. The sections are 2D, as optimized; nothing here invents a span.
FreeCAD is optional: `freecad_available()` is False without it and callers skip CAD files.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from swarm.cad.build import main_section, placed, write_coords
from swarm.ledger import RunFiles, best_passing, closest_candidate
from swarm.state import DesignSpec, EvalRecord, WingParams, free_params

DOC_SCRIPT = Path(__file__).with_name("freecad_doc.py")
AREA_TOL = 0.005  # relative; FreeCAD's B-spline face vs our polyline area
TIMEOUT_S = 180
POINTS = 161  # per surface, as the solvers use


class CadExportError(RuntimeError):
    pass


def freecad_cmd() -> str | None:
    return os.environ.get("AEROSWARM_FREECADCMD") or shutil.which("freecadcmd") or shutil.which("FreeCADCmd")


def freecad_available() -> bool:
    b = freecad_cmd()
    return bool(b) and os.access(b, os.X_OK)


PROBE_MARKER = "aeroswarm-freecad-ok"


@functools.lru_cache(maxsize=4)
def _probe(cmd: str) -> str | None:
    try:
        proc = subprocess.run(
            [cmd, "-c", f"print({PROBE_MARKER!r})"], capture_output=True, text=True, timeout=TIMEOUT_S
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"FreeCAD does not start: {e!r}"[:400]
    if PROBE_MARKER in proc.stdout:
        return None
    tail = (proc.stdout + proc.stderr).strip()[-300:]
    return f"FreeCAD is installed but does not start (exit {proc.returncode}): {tail}"


def freecad_probe() -> str | None:
    """None when `freecadcmd` actually starts here, else why not (checked once per command). Installed is not
    enough: FreeCAD 1.1.3 crashes at start-up when the process's user ID has no account entry (e.g. a container
    run with an arbitrary --user)."""
    cmd = freecad_cmd()
    if not cmd or not os.access(cmd, os.X_OK):
        return "FreeCAD (freecadcmd) is not installed"
    return _probe(cmd)


def polygon_area(xy: np.ndarray) -> float:
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def section_payload(
    name: str, label: str, params: WingParams, chord_mm: float, rec: EvalRecord | None, spec: DesignSpec
) -> dict:
    pts = placed(params, n=POINTS) * chord_mm
    le = pts[int(np.argmin(pts[:, 0]))]
    te = 0.5 * (pts[0] + pts[-1])
    r = rec.result if rec is not None else None
    return {
        "name": name,
        "label": label,
        "cid": params.cid,
        "params": {k: getattr(params, k) for k in free_params(spec)},
        "solver": r.fidelity if r else None,
        "cl": None if r is None or r.cl is None else round(r.cl, 5),
        "cd": None if r is None or r.cd is None else round(r.cd, 6),
        "verdict": rec.verdict.status if rec is not None and rec.verdict else None,
        "points_mm": np.round(pts, 5).tolist(),
        "chord_line_mm": [np.round(le, 5).tolist(), np.round(te, 5).tolist()],
        "expected_area_mm2": polygon_area(pts),
    }


def final_record(ledger: list[EvalRecord], spec: DesignSpec) -> tuple[EvalRecord | None, str]:
    rec = best_passing(ledger, spec)
    if rec is not None:
        return rec, "final (passing)"
    rec = closest_candidate(ledger, spec)
    return rec, "closest candidate (did not pass)"


def cad_for_viewer(run_dir: str | Path, viewer_runs: str | Path, rel_dir: str, name: str) -> dict | None:
    """The `cad` block of a viewer export: files written to viewer_runs/rel_dir, linked from the page.
    None when FreeCAD is not installed; {"error": ...} when the export failed (the run itself is unaffected)."""
    if not freecad_available():
        return None
    problem = freecad_probe()
    if problem:
        return {"error": problem}
    try:
        out = export_cad(run_dir, Path(viewer_runs) / rel_dir, name)
    except CadExportError as e:
        return {"error": str(e)[:500]}
    return {"dir": rel_dir, **out}


def export_cad(run_dir: str | Path, out_dir: str | Path, name: str) -> dict:
    """Build the CAD files for one run into `out_dir`. Returns {"files": {kind: filename}, "check": {...}}.
    Raises CadExportError when FreeCAD is missing, fails, or its geometry disagrees with ours."""
    cmd = freecad_cmd()
    if not cmd:
        raise CadExportError("FreeCAD (freecadcmd) is not installed; set AEROSWARM_FREECADCMD or install it")
    files = RunFiles(run_dir)
    meta = json.loads(files.meta.read_text())
    spec = DesignSpec.model_validate(meta["spec"])
    start = WingParams.model_validate(meta["start"])
    ledger = files.read_ledger()
    final, final_label = final_record(ledger, spec)
    if final is None:
        raise CadExportError("the run has no usable design to export")
    start_rec = next((r for r in ledger if r.params.cid == start.cid), None)
    chord = spec.car.chord_mm
    sections = [
        section_payload("final", f"Optimized: {final_label}", final.params, chord, final, spec),
        section_payload("start", "Start design", start, chord, start_rec, spec),
    ]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {"fcstd": out / f"{name}.FCStd", "step": out / f"{name}.step", "dat": out / f"{name}.dat"}
    for p in paths.values():  # a re-export replaces the files (FreeCAD would keep an .FCBak of an overwritten model)
        p.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        job = {
            "run_id": meta.get("run_id", Path(run_dir).name),
            "param_names": list(free_params(spec)),
            "sections": sections,
            "fcstd": str(paths["fcstd"].resolve()),
            "step": str(paths["step"].resolve()),
            "report": str(Path(tmp) / "report.json"),
        }
        job_path = Path(tmp) / "job.json"
        job_path.write_text(json.dumps(job))
        env = {**os.environ, "AEROSWARM_CAD_JOB": str(job_path)}
        try:
            proc = subprocess.run(
                [cmd, "-c", f"exec(open({str(DOC_SCRIPT)!r}).read())"],
                env=env,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            raise CadExportError(f"FreeCAD timed out after {TIMEOUT_S} s") from e
        report_path = Path(job["report"])
        if not report_path.exists():
            tail = (proc.stdout + proc.stderr).strip()[-600:]
            raise CadExportError(f"FreeCAD did not finish (exit {proc.returncode}): {tail}")
        report = json.loads(report_path.read_text())
    check = {"freecad_version": report["freecad_version"], "sections": {}}
    for sec in sections:
        got = report["sections"][sec["name"]]
        rel = abs(got["area_mm2"] - sec["expected_area_mm2"]) / sec["expected_area_mm2"]
        ok = bool(got["valid"]) and rel <= AREA_TOL
        check["sections"][sec["name"]] = {
            "cid": sec["cid"],
            "valid": got["valid"],
            "area_mm2": round(got["area_mm2"], 2),
            "expected_area_mm2": round(sec["expected_area_mm2"], 2),
            "area_rel_diff": round(rel, 6),
            "ok": ok,
        }
        if not ok:
            raise CadExportError(f"FreeCAD geometry check failed for the {sec['name']} section: {check}")
    if not (report["files"]["fcstd"] and report["files"]["step"]):
        raise CadExportError(f"FreeCAD did not write every file: {report['files']}")
    # the STEP file, read back: same faces, same areas (what another CAD program will open)
    step_areas = report.get("step_faces_mm2", [])
    expected = [sec["expected_area_mm2"] for sec in sections]
    step_ok = len(step_areas) == len(expected) and all(
        abs(a - e) / e <= AREA_TOL for a, e in zip(sorted(step_areas), sorted(expected), strict=True)
    )
    check["step_round_trip"] = {"faces": len(step_areas), "areas_mm2": [round(a, 2) for a in step_areas], "ok": step_ok}
    if not step_ok:
        raise CadExportError(f"the STEP file does not read back as the exported sections: {check['step_round_trip']}")
    write_coords(main_section(final.params, n=POINTS), paths["dat"], f"aeroswarm-{final.params.cid}")
    return {
        "files": {k: p.name for k, p in paths.items()},
        "final_cid": final.params.cid,
        "final_label": final_label,
        "chord_mm": chord,
        "check": check,
    }
