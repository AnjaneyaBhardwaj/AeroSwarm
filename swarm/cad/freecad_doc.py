"""Runs INSIDE FreeCAD (freecadcmd), not in the project's Python: builds the CAD document for one run.

    freecadcmd -c "exec(open('swarm/cad/freecad_doc.py').read())"   with AEROSWARM_CAD_JOB=<job.json>

The job file (written by swarm/cad/freecad_export.py) lists the sections to draw, each with its outline in mm
(race-car orientation, leading edge at the origin), its parameters and its ledger results. Output: a FreeCAD
document (.FCStd) with one group per section (closed B-spline face + chord line) and a "Design" spreadsheet,
a STEP file of the section faces, and a JSON report of what FreeCAD measured (validity, area, bounding box)
for the caller to cross-check against its own geometry. Standard library and FreeCAD modules only.
"""

import json
import os

import FreeCAD  # noqa: N813  (FreeCAD's own module names)
import Import
import Part

job = json.loads(open(os.environ["AEROSWARM_CAD_JOB"]).read())
doc = FreeCAD.newDocument("AeroSwarm")
report = {"freecad_version": ".".join(FreeCAD.Version()[:3]), "sections": {}}
faces = []


def section_face(points):
    """Closed face: an interpolated B-spline from trailing edge round the leading edge back to the trailing edge,
    plus the straight blunt-trailing-edge segment that closes it."""
    vs = [FreeCAD.Vector(x, y, 0.0) for x, y in points]
    curve = Part.BSplineCurve()
    curve.interpolate(vs)
    edges = [curve.toShape()]
    if (vs[0] - vs[-1]).Length > 1e-6:
        edges.append(Part.LineSegment(vs[-1], vs[0]).toShape())
    return Part.Face(Part.Wire(edges))


sheet = doc.addObject("Spreadsheet::Sheet", "Design")
sheet.set("A1", "AeroSwarm run")
sheet.set("B1", str(job["run_id"]))
sheet.set("A2", "units")
sheet.set("B2", "mm, race-car orientation (inverted, angle of attack applied), leading edge at origin")
row = 4
for col, head in enumerate(["section", "cid", "solver", "Cl", "Cd", "verdict"] + job["param_names"]):
    sheet.set(f"{chr(65 + col)}{row}", head)

for sec in job["sections"]:
    group = doc.addObject("App::DocumentObjectGroup", sec["name"].capitalize())
    group.Label = sec["label"]
    face = section_face(sec["points_mm"])
    obj = doc.addObject("Part::Feature", f"{sec['name']}_section")
    obj.Shape = face
    obj.Label = f"{sec['label']} section"
    le, te = sec["chord_line_mm"]
    chord = doc.addObject("Part::Feature", f"{sec['name']}_chord")
    chord.Shape = Part.LineSegment(FreeCAD.Vector(*le, 0), FreeCAD.Vector(*te, 0)).toShape()
    chord.Label = f"{sec['label']} chord line"
    group.addObjects([obj, chord])
    faces.append(obj)
    row += 1
    values = [sec["label"], sec["cid"], sec["solver"], sec["cl"], sec["cd"], sec["verdict"]]
    values += [sec["params"][n] for n in job["param_names"]]
    for col, v in enumerate(values):
        sheet.set(f"{chr(65 + col)}{row}", "" if v is None else str(v))
    bb = face.BoundBox
    # Area from a fine tessellation of the face: Face.Area's surface integration is inaccurate for a B-spline
    # boundary with hundreds of knots (6% low on a 321-point section, while the meshed face matches to 0.01%).
    verts, tris = face.tessellate(0.01)
    area = sum(((verts[b] - verts[a]).cross(verts[c] - verts[a])).Length / 2 for a, b, c in tris)
    report["sections"][sec["name"]] = {
        "valid": face.isValid(),
        "area_mm2": area,
        "bbox_mm": [bb.XMin, bb.YMin, bb.XMax, bb.YMax],
    }

doc.recompute()
doc.saveAs(job["fcstd"])
Import.export(faces, job["step"])
report["files"] = {"fcstd": os.path.exists(job["fcstd"]), "step": os.path.exists(job["step"])}


def mesh_area(shape):
    verts, tris = shape.tessellate(0.01)
    return sum(((verts[b] - verts[a]).cross(verts[c] - verts[a])).Length / 2 for a, b, c in tris)


# Round trip: what another CAD program reads from the STEP file (faces in export order)
back = Part.read(job["step"])
report["step_faces_mm2"] = [mesh_area(f) for f in back.Faces]
with open(job["report"], "w") as f:
    json.dump(report, f)
