"""The home page, "How it works" (viewer/index.html): every number on it is the example run's, from its export.

The page is hand-written for people new to the project, so this test is what keeps it in step with the ledger:
the result, the comic's generation 1, the rival's tries and the wing shapes drawn on it.
"""

import json
import re
from pathlib import Path

import pytest

VIEWER = Path("viewer")
EXPORT = VIEWER / "runs/example_hard_llm.json"


def minus(x: float, dp: int) -> str:
    return ("−" if x < 0 else "") + f"{abs(x):.{dp}f}"


@pytest.fixture(scope="module")
def ex():
    return json.loads(EXPORT.read_text())


@pytest.fixture(scope="module")
def html():
    return (VIEWER / "index.html").read_text()


@pytest.fixture(scope="module")
def text(html):
    """Visible words, tags removed and whitespace collapsed."""
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def test_result_numbers(ex, text):
    o, s = ex["outcome"], ex["spec"]
    assert o["result"] == "target_met" and o["solver"] == "xfoil"
    assert f"Target met on try {o['evals_to_target']}." in text
    assert f"This run needed {o['evals_to_target']} tries." in text
    assert f"Cl {minus(o['cl'], 4)}" in text and f"Cd {o['cd']:.4f}" in text
    assert f"target {minus(s['target_cl'], 2)} ± {s['cl_tol']:g}" in text and f"limit {s['cd_max']:g}" in text
    assert "the Tortoise (XFoil)" in text
    assert f"about ${ex['cost_usd']:.2f} of AI time, {round(ex['wall_hours'] * 60)} minutes" in text
    # the brief
    assert f"Cl {minus(s['target_cl'], 2)} , give or take {s['cl_tol']:g}" in text
    assert f"Cd {s['cd_max']:g}" in text


def test_comic_is_generation_one(ex, text):
    g = ex["generations"][1]
    ev = g["evals"][g["head"]]
    start = ex["start"]

    def change(name, label, scale, unit):
        return f"{label} {start[name] * scale:.2f} → {ev['params'][name] * scale:.2f}{unit}"

    assert g["gen"] == 1 and ev["parent_cid"] == ex["start_cid"]
    # 1. the Chief's plan: more camber, thinner, less angle
    focus = {f["name"]: f["direction"] for f in g["chief"]["focus"]}
    assert focus == {"main_camber": "+", "main_thickness": "-", "alpha_deg": "-"}
    assert "Bend it more, make it thinner and ease off the angle." in text
    # 2. the accepted sketch, and the rejected first one with the rulebook's numbers
    bubble = ", ".join(
        [
            change("main_camber", "camber", 100, "%"),
            change("main_thickness", "thickness", 100, "%"),
            change("alpha_deg", "angle", 1, "°"),
        ]
    )
    assert f"Take two: {bubble}." in text
    assert f"Camber {ev['params']['main_camber'] * 100:.2f}%, angle {ev['params']['alpha_deg']:.2f}°." in text
    first, second = g["cad"]
    assert (first["outcome"], second["outcome"]) == ("rejected", "accepted")
    got, need = re.search(r"([\d.]+) mm < ([\d.]+) mm", first["rejection"]).groups()
    assert f"({got} mm, the minimum is {need} mm)" in text
    # 3. the Hare's estimate and 4. the Critic's shortfall and diagnosis
    assert ev["solver"] == "neuralfoil"
    assert f"Cl {minus(ev['cl'], 2)}. The target is {minus(ex['spec']['target_cl'], 2)}." in text
    assert f"Still {abs(ev['cl'] - ex['spec']['target_cl']):.3f} short." in text
    assert g["critic"]["symptom"] == "EARLY_STALL" and "close to stalling" in text


def test_rival_is_the_optuna_baseline(ex, text):
    b = ex["baseline"]
    assert b["method"] == "optuna" and b["result"] == "no_pass"
    assert f"started from the same wing with {b['evals']} tries. It didn't find a passing design." in text


def test_wing_shapes_are_the_run_outlines(ex, html):
    for ident, cid in (("wing-final", ex["outcome"]["cid"]), ("wing-start", ex["start_cid"])):
        d = re.search(rf'<path id="{ident}"[^>]* d="([^"]+)"', html).group(1)
        assert d == "M" + "L".join(f"{x:.3f} {y:.3f}" for x, y in ex["outlines"][cid]) + "Z"


def test_home_page_and_replay_link_each_other(html):
    replay = (VIEWER / "replay.html").read_text()
    assert 'id="crew"' in html and 'id="stage"' in replay  # the explainer is the home page; the replay moved
    assert 'href="replay.html"' in html and 'href="./"' in replay
    # old addresses still lead somewhere: about.html to the home page, ?run= / ?gen= links on to the replay
    assert 'content="0; url=./"' in (VIEWER / "about.html").read_text()
    assert 'location.replace("replay.html" + location.search' in html
    for page in ("index.html", "replay.html", "about.html"):
        for ref in re.findall(r'(?:href|src)="([^"#:]+)"', (VIEWER / page).read_text()):
            target = VIEWER / ref
            assert (target / "index.html" if ref.endswith("/") else target).is_file(), (page, ref)


def test_conditions_are_the_runs(ex, text):
    """The page says what is optimized (one 2D slice) and under which conditions: the run's own."""
    from swarm.state import AIR_KINEMATIC_VISCOSITY

    speed, chord = ex["spec"]["speed_mps"], ex["cad"]["chord_mm"]
    assert speed * chord / 1000 / AIR_KINEMATIC_VISCOSITY == pytest.approx(ex["spec"]["reynolds"])
    assert f"tested in air at {speed:g} m/s ({speed * 3.6:g} km/h) on a slice {chord:g} mm long" in text
    assert f"Here {chord:g} mm." in text
    assert "Just the wing's cross-section, called an airfoil" in text
