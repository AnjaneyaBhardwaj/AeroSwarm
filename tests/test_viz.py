import imageio.v3 as iio

from swarm.state import BoundaryLayerSummary, CFDResult, Diagnosis, EvalRecord, Verdict, WingParams
from swarm.viz.evolution import blend, pick_frames, write_evolution


def rec(gen, alpha, cl, cd, symptom="INSUFFICIENT_LOADING", sep=None):
    p = WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=alpha)
    r = CFDResult(
        cid=p.cid,
        fidelity="xfoil",
        status="converged",
        cl=cl,
        cd=cd,
        bl=BoundaryLayerSummary(te_separation_xc=sep) if sep else None,
    )
    v = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom=symptom), confidence=0.6)
    return EvalRecord(generation=gen, params=p, result=r, verdict=v, rationale="")


LEDGER = [
    rec(0, 4, -0.8, 0.008),
    rec(1, 8, -1.3, 0.013),
    rec(2, 13, -1.45, 0.030, "TE_SEPARATION_MAIN", sep=0.8),
    rec(3, 10, -1.49, 0.016),
]


def test_pick_frames_prefers_te_separation(spec):
    first, middle, final = pick_frames(LEDGER, spec)
    assert (first.generation, middle.generation, final.generation) == (0, 2, 3)


def test_pick_frames_without_diagnosis_uses_biggest_drag_jump(spec):
    led = [rec(0, 4, -0.8, 0.008), rec(1, 8, -1.3, 0.020), rec(2, 9, -1.35, 0.021), rec(3, 10, -1.49, 0.016)]
    assert pick_frames(led, spec)[1].generation == 1


def test_blend_is_valid_params():
    a, b = LEDGER[0].params, LEDGER[3].params
    m = blend(a, b, 0.5)
    assert m.alpha_deg == 7.0 and isinstance(m, WingParams)


def test_write_evolution(spec, tmp_path):
    out = write_evolution(LEDGER, spec, tmp_path)
    strip = iio.imread(out["strip"])
    assert strip.ndim == 3 and strip.shape[1] > strip.shape[0] * 3
    gif = iio.imread(out["gif"])
    assert gif.shape[0] > 10  # recorded + interpolated + hold frames
