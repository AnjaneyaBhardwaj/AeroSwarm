import imageio.v3 as iio
from conftest import good_stall

from swarm.state import BoundaryLayerSummary, CFDResult, Diagnosis, EvalRecord, Verdict, WingParams
from swarm.viz.evolution import OK, SEP, _status, blend, pick_frames, stall_plot, write_evolution


def rec(gen, alpha, cl, cd, symptom="INSUFFICIENT_LOADING", sep=None, status="TARGET_MISS", stall=None, fid="xfoil"):
    p = WingParams(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=alpha)
    r = CFDResult(
        cid=p.cid,
        fidelity=fid,
        status="converged",
        cl=cl,
        cd=cd,
        bl=BoundaryLayerSummary(te_separation_xc=sep) if sep else None,
    )
    v = Verdict(status=status, diagnosis=Diagnosis(symptom=symptom), confidence=0.6)
    return EvalRecord(generation=gen, params=p, result=r, verdict=v, rationale="", stall_margin=stall)


def no_margin(slope):
    return good_stall(slope=slope).model_copy(update={"ok": False})


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


def test_middle_is_the_worst_stall_margin_and_never_the_after_cid(spec):
    led = [
        rec(0, 4, -0.8, 0.008),
        rec(1, 13, -1.45, 0.030, "TE_SEPARATION_MAIN", sep=0.8),  # earlier TE separation
        rec(2, 9, -1.48, 0.016, stall=no_margin(0.03)),
        rec(3, 10, -1.49, 0.016, stall=no_margin(0.01)),  # worst margin, but also the closest candidate
    ]
    first, middle, after = pick_frames(led, spec)
    assert after is led[3] and middle is led[2]  # worst margin among the others
    assert middle.params.cid != after.params.cid


def test_after_is_the_best_passing_design_even_if_a_failure_is_closer(spec):
    good = rec(2, 9, -1.52, 0.016, status="PASS", stall=good_stall())
    closer = rec(3, 10, -1.50, 0.016, stall=no_margin(0.02))
    first, middle, after = pick_frames([rec(0, 4, -0.8, 0.008), good, closer], spec)
    assert after is good and middle is closer


def test_frame_status_is_green_only_for_a_full_pass(spec):
    assert _status(rec(0, 9, -1.50, 0.016, status="PASS", stall=good_stall()), spec)[:2] == ("PASS", OK)
    text, colour, why = _status(rec(0, 9, -1.50, 0.016, status="PASS", fid="neuralfoil"), spec)
    assert colour == SEP and text.startswith("PASS at neuralfoil only") and why
    text, colour, why = _status(rec(0, 9, -1.50, 0.016, stall=no_margin(0.02)), spec)
    assert (text, colour) == ("TARGET_MISS", SEP) and why[0].startswith("stall_margin")


def test_stall_plot_written_per_probed_xfoil_candidate(spec, tmp_path):
    led = LEDGER + [rec(4, 10.5, -1.50, 0.016, stall=no_margin(0.02))]
    out = write_evolution(led, spec, tmp_path)
    cid = led[-1].params.cid
    assert out["stall_plots"] == {cid: str(tmp_path / f"stall_{cid}.png")}
    img = iio.imread(stall_plot(led[-1], spec, tmp_path / "s.png"))
    assert img.ndim == 3 and img.shape[1] > img.shape[0]


def test_middle_is_not_the_start_when_a_later_failure_exists(spec):
    from swarm.state import SurrogateScreen

    def screened(r, slope):
        sc = SurrogateScreen(
            alphas_deg=[1, 2, 3],
            cls=[-1, -1, -1],
            slopes=[slope, slope],
            dcl_dalpha=slope,
            stall_threshold=0.0575,
            stall_ok=False,
            h_sep=4.25,
            sep_warning=False,
            ok=False,
        )
        return r.model_copy(update={"screen": sc})

    led = [
        screened(rec(0, 12, -1.2, 0.040), -0.05),  # the start: worst screen slope of the run
        screened(rec(1, 9, -1.4, 0.020), 0.03),
        rec(2, 9.5, -1.49, 0.016, status="PASS", stall=good_stall()),
    ]
    first, middle, after = pick_frames(led, spec)
    assert after is led[2] and middle is led[1] and middle.params.cid != first.params.cid
    assert pick_frames(led[:1] + led[2:], spec)[1] is led[0]  # nothing else failed: the start it is
