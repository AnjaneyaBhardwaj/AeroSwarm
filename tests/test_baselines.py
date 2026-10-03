"""Benchmark baselines: seeded feasible starts and random search through the pipeline's gates."""

import json

from swarm.baselines import random_search, random_start
from swarm.cad.build import build
from swarm.run import HARD_SPEC, main
from swarm.solvers import neuralfoil
from swarm.state import WingParams


def test_random_start_is_seeded_and_feasible(tmp_path):
    a, b = random_start(11, HARD_SPEC), random_start(11, HARD_SPEC)
    assert a == b and a != random_start(22, HARD_SPEC)
    assert not build(a, HARD_SPEC, tmp_path).violations
    assert neuralfoil.evaluate(a, HARD_SPEC).cl < 0  # downforce


def test_random_search_promotes_through_the_screen_and_meets_the_target(spec, fake_xfoil, tmp_path):
    fake_xfoil(cl_offset=-0.05)  # XFoil a little more loaded than NeuralFoil: the promotion lands in the box
    start = WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.12, alpha_deg=6.6)
    out = random_search(spec.model_copy(update={"max_evals": 10}), start, seed=7, run_dir=tmp_path / "r")
    ledger = [json.loads(x) for x in (tmp_path / "r" / "ledger.jsonl").read_text().splitlines()]
    assert out["termination"] == "target_met" and out["evals"] == len(ledger) == 2
    assert [r["result"]["fidelity"] for r in ledger] == ["neuralfoil", "xfoil"]
    assert ledger[0]["screen"]["ok"] and ledger[1]["stall_margin"]["ok"] and ledger[1]["verdict"]["status"] == "PASS"
    meta = json.loads((tmp_path / "r" / "meta.json").read_text())
    assert meta["method"] == "random" and meta["start_seed"] == 7 and meta["best_passing_cid"] == start.cid
    assert (tmp_path / "r" / "report.md").exists()


def test_random_search_stops_at_the_evaluation_budget(spec, fake_xfoil, tmp_path):
    fake_xfoil(flat_probes=True)
    start = WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.12, alpha_deg=4.0)
    out = random_search(spec.model_copy(update={"max_evals": 6}), start, seed=3, run_dir=tmp_path / "b")
    assert out["termination"] == "eval_budget" and out["evals"] == 6
    ledger = [json.loads(x) for x in (tmp_path / "b" / "ledger.jsonl").read_text().splitlines()]
    assert ledger[0]["params"] == start.model_dump() and ledger[0]["rationale"] == "baseline"
    assert all(
        r["rationale"] in ("baseline", "random sample") or r["rationale"].startswith("promotion") for r in ledger
    )


def test_cli_start_seed_is_recorded(tmp_path, fake_xfoil):
    fake_xfoil()
    main(
        [
            "--llm",
            "mock",
            "--preset",
            "hard",
            "--max-evals",
            "2",
            "--start-seed",
            "11",
            "--max-wall-hours",
            "1.5",
            "--runs-root",
            str(tmp_path),
            "--run-id",
            "s",
        ]
    )
    meta = json.loads((tmp_path / "s" / "meta.json").read_text())
    assert meta["start_seed"] == 11 and meta["start"] == random_start(11, HARD_SPEC).model_dump()
    assert meta["spec"]["max_wall_hours"] == 1.5
