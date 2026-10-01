"""The hard demo preset (make demo-hard) against the real XFoil binary.

Target = 85% of attached Cl,max (docs/PROGRESS.md, session 3). With the mock the run is
deterministic: a TE-separated TARGET_MISS becomes the strip's middle frame, and designs in
the box without a stall margin are rejected.
"""

import json

import pytest

from swarm.run import HARD_SPEC, HARD_START, PRESETS, main, run
from swarm.solvers.xfoil import xfoil_available
from swarm.viz.evolution import pick_frames


def test_hard_preset_is_registered():
    assert PRESETS["hard"] == (HARD_SPEC, HARD_START)
    assert HARD_SPEC.reynolds == pytest.approx(3.0e5, rel=1e-3) and HARD_SPEC.target_cl == -1.78


@pytest.mark.xfoil
@pytest.mark.skipif(not xfoil_available(), reason="xfoil binary not installed")
def test_hard_demo_separation_and_stall_margin_gates(tmp_path):
    """Near-stall designs are no longer accepted: the retuned target sits at ~85% of attached
    Cl,max, so the run meets TE separation and in-box designs with no stall margin."""
    final = run(HARD_SPEC, HARD_START, run_id="hard", runs_root=tmp_path, which="mock", inject_faults=True)
    ledger = final["ledger"]
    xf = [r for r in ledger if r.result.fidelity == "xfoil"]
    sep = [r for r in xf if r.verdict.diagnosis.symptom == "TE_SEPARATION_MAIN"]
    assert sep and sep[0].result.bl.te_separation_xc is not None and sep[0].result.bl.cf_te < 0
    assert all(r.verdict.status == "TARGET_MISS" for r in sep)  # separated rounds are never PASS
    # in the box at the design alpha, attached, but no margin: TARGET_MISS with the margin logged
    nomargin = [r for r in xf if r.stall_margin is not None and not r.stall_margin.ok]
    assert nomargin and all(r.verdict.status == "TARGET_MISS" for r in nomargin)
    assert all(
        r.stall_margin.dcl_dalpha is None or r.stall_margin.dcl_dalpha < r.stall_margin.threshold for r in nomargin
    )
    # invariant for any path: an XFoil PASS is attached and carries a passing margin
    for r in xf:
        if r.verdict.status == "PASS":
            assert r.result.bl.te_separation_xc is None and r.stall_margin is not None and r.stall_margin.ok
    if final["termination"] == "target_met":
        assert ledger[-1].stall_margin.ok
    first, middle, last = pick_frames(ledger, HARD_SPEC)
    assert middle is sep[0] and first is not middle and last is not middle
    assert (tmp_path / "hard" / "evolution_strip.png").stat().st_size > 1000


def test_cli_preset_and_max_evals(tmp_path, fake_xfoil, capsys):
    fake_xfoil()
    main(["--llm", "mock", "--preset", "hard", "--max-evals", "2", "--runs-root", str(tmp_path), "--run-id", "c"])
    meta = json.loads((tmp_path / "c" / "meta.json").read_text())
    assert meta["preset"] == "hard" and meta["spec"]["max_evals"] == 2 and meta["spec"]["target_cl"] == -1.78
    assert meta["evals"] == 2 and meta["termination"] == "budget"
    assert '"preset": "hard"' in capsys.readouterr().out
