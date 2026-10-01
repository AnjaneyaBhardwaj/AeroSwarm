"""The hard demo preset (make demo-hard) against the real XFoil binary.

Deterministic with the mock: the promotion to XFoil needs a ladder recovery and
comes back with TE separation, which becomes the strip's middle frame.
"""

import json

import pytest

from swarm.run import HARD_SPEC, HARD_START, PRESETS, main, run
from swarm.solvers.xfoil import xfoil_available
from swarm.viz.evolution import pick_frames


def test_hard_preset_is_registered():
    assert PRESETS["hard"] == (HARD_SPEC, HARD_START)
    assert HARD_SPEC.reynolds == pytest.approx(3.0e5, rel=1e-3) and HARD_SPEC.target_cl == -2.0


@pytest.mark.xfoil
@pytest.mark.skipif(not xfoil_available(), reason="xfoil binary not installed")
def test_hard_demo_triggers_ladder_and_te_separation(tmp_path):
    final = run(HARD_SPEC, HARD_START, run_id="hard", runs_root=tmp_path, which="mock", inject_faults=True)
    events = [json.loads(x) for x in (tmp_path / "hard" / "events.jsonl").read_text().splitlines()]
    rec = [e for e in events if e.get("event") == "xfoil_recovery"]
    assert rec and rec[0]["from_level"] == 0 and rec[0]["signature"] == "not_converged@L0"
    assert not any(e.get("event") == "xfoil_ladder_exhausted" for e in events)
    ledger = final["ledger"]
    sep = [r for r in ledger if r.verdict.diagnosis.symptom == "TE_SEPARATION_MAIN"]
    assert sep and sep[0].result.fidelity == "xfoil" and sep[0].result.solver_level >= 1
    assert sep[0].result.bl.te_separation_xc is not None and sep[0].result.bl.cf_te < 0
    assert sep[0].verdict.status == "TARGET_MISS"  # the separated round is a real middle, not the end
    first, middle, last = pick_frames(ledger, HARD_SPEC)
    assert middle is sep[0] and first is not middle and last is not middle
    assert final["termination"] == "target_met"
    assert (tmp_path / "hard" / "evolution_strip.png").stat().st_size > 1000


def test_cli_preset_and_max_evals(tmp_path, fake_xfoil, capsys):
    fake_xfoil()
    main(["--llm", "mock", "--preset", "hard", "--max-evals", "2", "--runs-root", str(tmp_path), "--run-id", "c"])
    meta = json.loads((tmp_path / "c" / "meta.json").read_text())
    assert meta["preset"] == "hard" and meta["spec"]["max_evals"] == 2 and meta["spec"]["target_cl"] == -2.0
    assert meta["evals"] == 2 and meta["termination"] == "budget"
    assert '"preset": "hard"' in capsys.readouterr().out
