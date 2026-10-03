"""The hard demo preset (make demo-hard).

Target = 85% of attached Cl,max (docs/PROGRESS.md, session 3). With the mock the run is
deterministic. Its alpha-led path stays at alpha ~9-9.5 deg on 6-8% camber sections, where
NeuralFoil and XFoil agree there is no stall margin (session 6), so the NeuralFoil screen
blocks every near-target candidate and none is promoted to XFoil.
"""

import json

import pytest

from swarm.briefs import near_target, screen_blocked
from swarm.run import HARD_SPEC, HARD_START, PRESETS, main, run
from swarm.solvers.xfoil import xfoil_available
from swarm.viz.evolution import pick_frames


def test_hard_preset_is_registered():
    assert PRESETS["hard"] == (HARD_SPEC, HARD_START)
    assert HARD_SPEC.reynolds == pytest.approx(3.0e5, rel=1e-3) and HARD_SPEC.target_cl == -1.83


@pytest.mark.xfoil
@pytest.mark.skipif(not xfoil_available(), reason="xfoil binary not installed")
def test_hard_demo_screen_blocks_near_stall_promotions(tmp_path):
    final = run(HARD_SPEC, HARD_START, run_id="hard", runs_root=tmp_path, which="mock", inject_faults=True)
    ledger = final["ledger"]
    near = near_target(ledger, HARD_SPEC)
    assert near and all(screen_blocked(r) for r in near)
    assert all(r.verdict.status == "TARGET_MISS" and "neuralfoil_screen" in r.failed_checks for r in near)
    # nothing the screen failed reached XFoil
    nf = {r.params.cid: r for r in ledger if r.result.fidelity == "neuralfoil"}
    for r in ledger:
        if r.result.fidelity == "xfoil" and r.params.cid in nf:
            assert nf[r.params.cid].screen.ok
        if r.result.fidelity == "xfoil" and r.verdict.status == "PASS":  # invariant for any path
            assert r.result.bl.te_separation_xc is None and r.stall_margin is not None and r.stall_margin.ok
    assert final["termination"] != "target_met"
    first, middle, last = pick_frames(ledger, HARD_SPEC)
    assert middle.params.cid != last.params.cid
    report = (tmp_path / "hard" / "report.md").read_text()
    assert "## Best passing design\n\n**None.**" in report and "NeuralFoil stall screen" in report
    assert (tmp_path / "hard" / "evolution_strip.png").stat().st_size > 1000


def test_cli_preset_and_max_evals(tmp_path, fake_xfoil, capsys):
    fake_xfoil()
    main(["--llm", "mock", "--preset", "hard", "--max-evals", "2", "--runs-root", str(tmp_path), "--run-id", "c"])
    meta = json.loads((tmp_path / "c" / "meta.json").read_text())
    assert meta["preset"] == "hard" and meta["spec"]["max_evals"] == 2 and meta["spec"]["target_cl"] == -1.83
    assert meta["evals"] == 2 and meta["termination"] == "eval_budget"
    assert '"preset": "hard"' in capsys.readouterr().out
