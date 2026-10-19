"""CAD files of a run (swarm/cad/freecad_export.py): geometry handed to FreeCAD, and the export itself
(that part needs FreeCAD's `freecadcmd`, else it is skipped; set AEROSWARM_FREECADCMD to point at it)."""

import json

import numpy as np
import pytest

from swarm.cad import freecad_export as fx
from swarm.cad.build import placed
from swarm.ledger import RunFiles
from swarm.state import DesignSpec

EXAMPLE = "runs/examples/hard_llm_20261001-201455-faf6a3"


def _example():
    files = RunFiles(EXAMPLE)
    meta = json.loads(files.meta.read_text())
    return DesignSpec.model_validate(meta["spec"]), files.read_ledger()


def test_polygon_area():
    assert fx.polygon_area(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)) == pytest.approx(1.0)


def test_final_record_is_the_best_passing_design():
    spec, ledger = _example()
    rec, label = fx.final_record(ledger, spec)
    assert rec.params.cid == "abb9803ead" and rec.result.fidelity == "xfoil" and label == "final (passing)"


def test_section_payload_is_real_scale_and_carries_ledger_values():
    spec, ledger = _example()
    rec, _ = fx.final_record(ledger, spec)
    sec = fx.section_payload("final", "Optimized", rec.params, 300.0, rec, spec)
    pts = np.array(sec["points_mm"])
    assert len(pts) == 2 * fx.POINTS - 1
    chord = np.hypot(*(np.array(sec["chord_line_mm"][1]) - np.array(sec["chord_line_mm"][0])))
    assert chord == pytest.approx(300.0, rel=0.01)  # leading edge to trailing-edge midpoint
    assert sec["expected_area_mm2"] == pytest.approx(fx.polygon_area(placed(rec.params, n=fx.POINTS) * 300.0))
    assert sec["cl"] == pytest.approx(rec.result.cl, abs=1e-5) and sec["verdict"] == "PASS"
    assert set(sec["params"]) == {"main_camber", "main_camber_pos", "main_thickness", "alpha_deg"}


def test_without_freecad_nothing_is_built(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "freecad_cmd", lambda: None)
    assert fx.cad_for_viewer(EXAMPLE, tmp_path, "x_cad", "x") is None
    with pytest.raises(fx.CadExportError, match="not installed"):
        fx.export_cad(EXAMPLE, tmp_path, "x")
    assert not any(tmp_path.iterdir())


@pytest.mark.freecad
@pytest.mark.skipif(not fx.freecad_available(), reason="needs FreeCAD (freecadcmd or AEROSWARM_FREECADCMD)")
def test_freecad_export_round_trip(tmp_path):
    out = fx.cad_for_viewer(EXAMPLE, tmp_path, "ex_cad", "ex")
    assert "error" not in out, out
    assert out["dir"] == "ex_cad" and out["final_cid"] == "abb9803ead"
    for f in out["files"].values():
        assert (tmp_path / "ex_cad" / f).stat().st_size > 1000
    secs = out["check"]["sections"]
    assert all(s["ok"] and s["valid"] and s["area_rel_diff"] < 1e-3 for s in secs.values())
    assert out["check"]["step_round_trip"] == {**out["check"]["step_round_trip"], "faces": 2, "ok": True}
    dat = (tmp_path / "ex_cad" / "ex.dat").read_text().splitlines()
    assert dat[0] == "aeroswarm-abb9803ead" and len(dat) == 2 * fx.POINTS
