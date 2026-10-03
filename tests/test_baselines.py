"""Benchmark baselines: seeded feasible starts and random search through the pipeline's gates."""

import json

from swarm.baselines import _TPE, INFEASIBLE_VALUE, TPE_LABEL, optuna_search, random_search, random_start, tpe_value
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


# ----------------------------------------------------------- Optuna TPE


def _ledger(path):
    return [json.loads(x) for x in (path / "ledger.jsonl").read_text().splitlines()]


def test_optuna_search_is_seeded_and_runs_through_the_same_gates(spec, fake_xfoil, tmp_path):
    fake_xfoil(flat_probes=True)
    start = WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.12, alpha_deg=4.0)
    s6 = spec.model_copy(update={"max_evals": 6})
    a = optuna_search(s6, start, seed=5, run_dir=tmp_path / "a")
    optuna_search(s6, start, seed=5, run_dir=tmp_path / "b")
    optuna_search(s6, start, seed=6, run_dir=tmp_path / "c")
    la, lb, lc = _ledger(tmp_path / "a"), _ledger(tmp_path / "b"), _ledger(tmp_path / "c")
    assert a["termination"] == "eval_budget" and a["evals"] == len(la) == 6
    assert [r["params"] for r in la] == [r["params"] for r in lb] != [r["params"] for r in lc]
    assert la[0]["params"] == start.model_dump() and la[0]["rationale"] == "baseline"
    assert all(r["rationale"] in ("baseline", "tpe sample") or r["rationale"].startswith("promotion") for r in la)
    assert all(r["screen"] is not None for r in la if r["result"]["cl"] is not None)  # the NeuralFoil screen ran
    meta = json.loads((tmp_path / "a" / "meta.json").read_text())
    assert meta["method"] == "optuna" and meta["start_seed"] == 5 and meta["llm_client"] == TPE_LABEL


def test_optuna_search_promotes_and_meets_the_target(spec, fake_xfoil, tmp_path):
    fake_xfoil(cl_offset=-0.05)
    start = WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.12, alpha_deg=6.6)
    out = optuna_search(spec.model_copy(update={"max_evals": 10}), start, seed=7, run_dir=tmp_path / "o")
    assert out["termination"] == "target_met" and out["evals"] == 2
    assert [r["result"]["fidelity"] for r in _ledger(tmp_path / "o")] == ["neuralfoil", "xfoil"]


def _rec(p, cl, fid="neuralfoil", screen_slope=0.08):
    from test_loop_fixes import screen

    from swarm.state import CFDResult, EvalRecord

    r = CFDResult(cid=p.cid, fidelity=fid, status="converged", cl=cl, cd=0.017)
    return EvalRecord(generation=0, params=p, result=r, verdict=None, rationale="", screen=screen(slope=screen_slope))


def test_tpe_value_is_the_constraint_violation(spec):
    p = WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.12, alpha_deg=6.6)
    in_box, stalled, far = _rec(p, -1.50), _rec(p, -1.50, screen_slope=0.025), _rec(p, -1.20)
    assert tpe_value(in_box, spec) < 0.01 < tpe_value(stalled, spec) < tpe_value(far, spec)
    assert tpe_value(_rec(p, None), spec) == INFEASIBLE_VALUE


def test_tpe_proposer_records_the_start_rejections_and_xfoil_results(spec):
    start = WingParams(main_camber=0.06, main_camber_pos=0.40, main_thickness=0.12, alpha_deg=6.6)
    tpe = _TPE(spec, start, seed=1)
    tpe.tell(start, _rec(start, -1.45))  # the start: an added trial
    q = tpe.ask()
    assert q != start and q.flap_chord_ratio == start.flap_chord_ratio  # only free parameters move
    tpe.reject(q)  # infeasible geometry
    tpe.tell(start, _rec(start, -1.40, fid="xfoil"))  # XFoil result of the promoted start
    vals = [t.value for t in tpe.study.trials]
    assert vals[1] == INFEASIBLE_VALUE and len(vals) == 3
    assert tpe.study.trials[2].params == tpe.study.trials[0].params == {n: getattr(start, n) for n in tpe.names}
