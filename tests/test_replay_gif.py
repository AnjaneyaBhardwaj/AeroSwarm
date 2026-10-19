"""README replay GIF (swarm/viz/replay_gif.py): numbers from the export, morphs through parameters, valid GIFs."""

import copy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageSequence

from swarm.state import WingParams
from swarm.viz.export import outline
from swarm.viz.replay_gif import (
    THEMES,
    Frame,
    cl_txt,
    facts,
    head,
    load,
    plan,
    recorded,
    save_gif,
    shape,
    status_of,
    write_gif,
)

EXPORT = Path("viewer/runs/example_hard_llm.json")


@pytest.fixture(scope="module")
def ex():
    return load(EXPORT)


def first_generations(ex, n):
    """The first n recorded generations as a self-contained export (fast to render)."""
    e = copy.deepcopy(ex)
    e["generations"] = recorded(e)[:n]
    return e


def test_plan_holds_each_generation_once_and_keeps_time(ex):
    kw = {"hold_ms": 300, "tween": 3, "tween_ms": 40, "first_ms": 800, "final_ms": 2000}
    frames = plan(ex, **kw)
    n = len(recorded(ex))
    assert [f.i for f in frames if f.f == 0] == list(range(n))
    assert frames[-1].final and sum(f.final for f in frames) == 1
    for prev, f in zip(frames, frames[1:], strict=False):
        if f.f:  # a morph frame continues from the recorded frame before it
            assert 0 < f.f < 1 and f.i == prev.i and f.f > prev.f
    # skipped morphs move their time into the hold, so the loop length is fixed
    assert sum(f.ms for f in frames) == 800 + (n - 2) * 300 + 2000 + (n - 1) * 3 * 40


def test_plan_skips_the_morph_between_two_frames_of_one_design(ex):
    e = first_generations(ex, 2)
    a, b = head(e["generations"][0]), head(e["generations"][1])
    b["cid"], b["params"] = a["cid"], a["params"]  # e.g. an XFoil check of the design just shown
    frames = plan(e)
    assert all(f.f == 0 for f in frames) and len(frames) == 2


def test_every_number_is_the_recorded_headline_record(ex):
    rec = recorded(ex)
    for f in plan(ex):
        fx, ev = facts(ex, f), head(rec[f.i])
        assert (fx["gen"], fx["cl"], fx["cd"]) == (rec[f.i]["gen"], cl_txt(ev["cl"]), f"{ev['cd']:.5f}")
        assert fx["status"] == status_of(ev)[0]
        # a morph frame says where it is going and carries no numbers of its own
        assert fx["interpolated"] == (0 < f.f < 1)
        assert fx["toward"] == (rec[f.i + 1]["gen"] if fx["interpolated"] else None)


def test_last_frame_states_the_outcome(ex):
    fx = facts(ex, plan(ex)[-1])
    o = ex["outcome"]
    assert fx["footer"].startswith(f"Target met in {o['evals_to_target']} evaluations")
    assert cl_txt(o["cl"]) in fx["footer"] and fx["footer_kind"] == "pass"
    assert facts(ex, plan(ex)[0])["footer"].startswith("Goal: Cl −1.83 ± 0.03 and Cd ≤ 0.025")

    e = copy.deepcopy(ex)
    e["outcome"] = {"result": "no_pass", "cid": None, "cl": None, "cd": None, "solver": None, "failing": []}
    e["is_mock"] = True
    fx = facts(e, plan(e)[-1])
    assert fx["footer"] == f"No passing design in {e['evals']} evaluations (mock run, not an LLM)"
    assert fx["footer_kind"] == "miss"


def test_status_labels():
    assert status_of({"passing": True, "verdict": "PASS", "solver": "xfoil"}) == ("PASS", "pass")
    assert status_of({"passing": False, "verdict": "PASS", "solver": "neuralfoil"}) == (
        "PASS at NeuralFoil only",
        "miss",
    )
    assert status_of({"passing": False, "verdict": "TARGET_MISS", "solver": "xfoil"}) == ("TARGET MISS", "miss")
    assert status_of({"passing": False, "verdict": None, "solver_status": "diverged", "solver": "xfoil"}) == (
        "diverged",
        "fail",
    )


def test_morph_goes_through_parameters(ex):
    rec = recorded(ex)
    a, b = head(rec[0]), head(rec[1])
    recorded_outline = np.asarray(ex["outlines"][a["cid"]])
    assert np.allclose(shape(ex, Frame(0)), recorded_outline)
    # the export's outlines are the exporter's own outline() of the recorded parameters
    assert np.allclose(outline(WingParams(**a["params"])), recorded_outline, atol=1e-6)
    mid = {k: (a["params"][k] + b["params"][k]) / 2 for k in a["params"]}
    between = shape(ex, Frame(0, 0.5))
    assert between.shape == recorded_outline.shape
    assert np.allclose(between, outline(WingParams(**mid)))


def test_palette_keeps_reserved_colours(tmp_path):
    bg, red = (252, 252, 251), (208, 59, 59)
    imgs = [np.full((20, 30, 3), bg, dtype=np.uint8) for _ in range(20)]
    imgs[3][5:10, 5:10] = red  # only in a frame the palette sample skips
    path = save_gif(imgs, [50] * 20, tmp_path / "p.gif", colors=16, keep=("#d03b3b", "#fcfcfb"))
    decoded = [np.asarray(f.convert("RGB")) for f in ImageSequence.Iterator(Image.open(path))]
    colours = {tuple(px) for f in decoded for px in f.reshape(-1, 3)}
    assert colours == {bg, red}  # exact, and identical frames merged by the writer keep their time
    assert sum(f.info["duration"] for f in ImageSequence.Iterator(Image.open(path))) == 1000


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_write_gif(ex, tmp_path, theme):
    e = first_generations(ex, 3)
    path = write_gif(e, tmp_path / f"{theme}.gif", theme=theme, dpi=40)
    im = Image.open(path)
    durations = [f.info["duration"] for f in ImageSequence.Iterator(im)]
    assert im.info["loop"] == 0 and im.size == (384, 164)
    assert sum(durations) == sum(f.ms for f in plan(e)) and len(durations) <= len(plan(e))
    first = np.asarray(Image.open(path).convert("RGB"))
    assert tuple(first[2, 2]) == tuple(int(THEMES[theme]["bg"][i : i + 2], 16) for i in (1, 3, 5))


def test_readme_alt_text_matches_the_export(ex):
    readme = Path("README.md").read_text()
    o = ex["outcome"]
    assert f"generation {o['generation']} reaches the target box (Cl {cl_txt(o['cl'])}, Cd {o['cd']:.4f}" in readme
    assert all((Path("docs/media") / f"replay-{t}.gif").is_file() for t in THEMES)
