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


def test_the_tortoise_catch_is_the_runs_own(ex, text):
    """Rounds 7 and 8: the Hare's screen passed a wing, the Tortoise re-tested the same wing and sent it back.
    The charts are the run folder's own files; the numbers are read from the export."""
    gens = ex["generations"]
    screened, caught, final = (gens[i]["evals"][0] for i in (7, 8, 22))
    assert (screened["solver"], screened["verdict"], caught["solver"]) == ("neuralfoil", "PASS", "xfoil")
    assert screened["cid"] == caught["cid"] and caught["stall"]["ok"] is False and caught["symptom"] == "EARLY_STALL"
    assert final["cid"] == ex["outcome"]["cid"] and final["stall"]["ok"] is True
    note = next(n for n in gens[8]["notes"] if n["event"] == "screen_xfoil_disagreement")
    assert note["stall"]["screen_ok"] is True
    bar = caught["stall"]["threshold"]
    assert final["stall"]["threshold"] == bar and f"at least {bar:g} more Cl for each extra degree" in text
    screen_slope = note["stall"]["screen_dcl_dalpha"]
    assert f"In round 7 the Hare's quick estimate passed this wing at {screen_slope:.3f} per degree" in text
    assert "Round 8: sent back." in text and f"measured {caught['stall']['dcl_dalpha']:.3f}." in text
    assert f"Round 22: official. The final wing gains {final['stall']['dcl_dalpha']:.3f} per degree" in text
    run_dir = next(Path("runs/examples").glob(f"*{ex['run_id']}"))
    for e in (caught, final):
        shown = VIEWER / "media" / f"stall_{e['cid']}.png"
        assert shown.read_bytes() == (run_dir / shown.name).read_bytes()


def test_flipbook_reads_the_export(ex, html, text):
    """Every try, from the export; without it the static start and final shapes stay."""
    assert f"Flip through all {ex['evals']} tries" in text
    assert f'max="{ex["evals"]}" step="1" value="{ex["evals"]}"' in html
    assert ex["evals"] == sum(len(g["evals"]) for g in ex["generations"])
    js = (VIEWER / "about.js").read_text()
    assert 'fetch("runs/example_hard_llm.json"' in js
    assert re.search(r'<script src="about\.js\?v=\w+" defer></script>', html)


def test_rulebook_note_is_the_codes_own_check(ex, text):
    """The run's rulebook comes from its spec; the FSAE 2027 claims are swarm.cad.regulations' own check of the run's
    designs on the car the run used."""
    from swarm.cad.build import placed_mm
    from swarm.cad.regulations import RULEBOOKS, check_regulations
    from swarm.state import PLACEHOLDER_CAR, DesignSpec, WingParams

    assert ex["spec"]["rulebook"] == "FS2026_v1.1" and DesignSpec.model_fields["car"].default == PLACEHOLDER_CAR
    assert DesignSpec.model_fields["rulebook"].default == "FSAE2027_v1.0"
    assert "Legal under the Formula Student 2026 rules" in text
    assert "This run was checked against the Formula Student 2026 rules." in text
    assert "The project now follows the Formula SAE 2027 rulebook" in text
    fs, fsae = RULEBOOKS["FS2026_v1.1"], RULEBOOKS["FSAE2027_v1.0"]
    assert f"a {fsae.le_radius_min.value:g} mm radius instead of {fs.le_radius_min.value:g} mm" in text

    def violations(params, rulebook):
        p = WingParams(**params)
        return check_regulations(placed_mm(p, PLACEHOLDER_CAR), p, PLACEHOLDER_CAR, rulebook)

    tries = [e for g in ex["generations"] for e in g["evals"]]
    assert all(not violations(e["params"], "FS2026_v1.1") for e in tries)  # legal under the run's own rulebook
    # "new runs start from a thicker wing": both presets start thicker, and legal under FSAE 2027
    from swarm.run import PRESETS

    assert "This run's wings were shaped for the older rule, so new runs start from a thicker wing." in text
    for spec, start in PRESETS.values():
        assert spec.rulebook == "FSAE2027_v1.0" and start.main_thickness > ex["start"]["main_thickness"]
        assert not violations(start.model_dump(), "FSAE2027_v1.0")


def test_home_page_and_replay_link_each_other(html):
    replay = (VIEWER / "replay.html").read_text()
    assert 'id="crew"' in html and 'id="stage"' in replay  # the explainer is the home page; the replay moved
    assert 'href="replay.html"' in html and 'href="./"' in replay
    # old addresses still lead somewhere: about.html to the home page, ?run= / ?gen= links on to the replay
    assert 'content="0; url=./"' in (VIEWER / "about.html").read_text()
    assert 'location.replace("replay.html" + location.search' in html
    for page in ("index.html", "replay.html", "about.html"):
        for ref in re.findall(r'(?:href|src)="([^"#:?]+)(?:\?v=\w+)?"', (VIEWER / page).read_text()):
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
