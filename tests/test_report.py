"""report.md never calls a TARGET_MISS "best"; termination says which limit ended the run."""

import json
import time

import pytest
from conftest import good_stall

from swarm.graph import termination_reason
from swarm.ledger import best_passing, closest_candidate, failing_checks, passing
from swarm.run import run
from swarm.state import BoundaryLayerSummary, CFDResult, Diagnosis, EvalRecord, StallMargin, Verdict, WingParams


def rec(gen, cl, cd, fidelity="xfoil", status="TARGET_MISS", stall=None, alpha=8.0, sep=None, failed=()):
    p = WingParams(main_camber=0.05, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=alpha)
    r = CFDResult(
        cid=p.cid,
        fidelity=fidelity,
        status="converged",
        cl=cl,
        cd=cd,
        bl=BoundaryLayerSummary(te_separation_xc=sep) if sep else None,
    )
    v = Verdict(status=status, diagnosis=Diagnosis(symptom="NONE"), confidence=0.7)
    return EvalRecord(
        generation=gen, params=p, result=r, verdict=v, rationale="", stall_margin=stall, failed_checks=list(failed)
    )


NO_MARGIN = StallMargin(
    alphas_deg=[9.0, 10.0, 11.0],
    cls=[-1.5, -1.526, -1.54],
    levels=[0, 0, 0],
    te_separation_xc=[None, 0.97, 0.91],
    slopes=[0.026, 0.014],
    dcl_dalpha=0.014,
    threshold=0.05,
    ok=False,
)


# ----------------------------------------------------------- ledger helpers


def test_only_an_xfoil_pass_is_passing(spec):
    assert passing(rec(0, -1.5, 0.017, status="PASS", stall=good_stall()))
    assert not passing(rec(0, -1.5, 0.017, fidelity="neuralfoil", status="PASS"))
    assert not passing(rec(0, -1.5, 0.017, status="TARGET_MISS", stall=NO_MARGIN))
    fb = rec(0, -1.5, 0.017, status="PASS").model_copy(deep=True)
    fb.result.fallback_from = "xfoil"
    assert not passing(fb)


def test_closest_candidate_prefers_terminal_fidelity_and_explains_itself(spec):
    nf = rec(0, -1.500, 0.017, fidelity="neuralfoil", status="PASS", alpha=7.0)
    xf = rec(1, -1.497, 0.017, stall=NO_MARGIN, alpha=8.0, failed=["stall_margin"])
    far = rec(2, -1.30, 0.017, alpha=9.0)
    ledger = [nf, xf, far]
    assert best_passing(ledger, spec) is None
    assert closest_candidate(ledger, spec) is xf  # nf has the lower objective but was never checked at XFoil
    why = failing_checks(xf, spec)
    assert why == ["stall_margin: d|Cl|/dα 0.014/deg < 0.05 (TE separation x/c 0.97 at 10°, x/c 0.91 at 11°)"]
    assert failing_checks(far, spec)[0].startswith("target box: Cl -1.3000 is 0.2000 from -1.5")
    assert any(w.startswith("fidelity: neuralfoil only") for w in failing_checks(nf, spec))
    sep = rec(3, -1.5, 0.019, sep=0.9, failed=["te_separation"])
    assert failing_checks(sep, spec) == [
        "target box: Cd 0.01900 > cd_max 0.018",
        "te_separation: suction-side Cf < 0 from x/c 0.90 to the TE",
    ]


def test_best_passing_ignores_closer_failures(spec):
    good = rec(0, -1.52, 0.017, status="PASS", stall=good_stall(), alpha=7.0)
    closer = rec(1, -1.50, 0.017, stall=NO_MARGIN, alpha=8.0)
    assert best_passing([good, closer], spec) is good and failing_checks(good, spec) == []


# ----------------------------------------------------------- termination


def _state(spec, n=0, started=None, **kw):
    return {"spec": spec, "ledger": [rec(i, -1.3, 0.017) for i in range(n)], "started_at": started, **kw}


def test_termination_labels_name_the_limit(spec):
    s = spec.model_copy(update={"max_evals": 3, "max_wall_hours": 0.5})
    assert termination_reason(_state(s, n=3, started=time.time())) == "eval_budget"
    assert termination_reason(_state(s, n=1, started=time.time() - 3600)) == "wall_clock"
    assert termination_reason(_state(s, n=3, started=time.time()), cost_capped=True) == "cost_cap"
    assert termination_reason(_state(s, n=1, started=time.time())) == "unknown"
    assert termination_reason(_state(s, n=3, started=time.time()), invalid=True) == "invalid_llm"


# ----------------------------------------------------------- report.md / meta.json


def test_report_without_a_pass_shows_none_and_the_closest_candidate(spec, start, fake_xfoil, tmp_path):
    fake_xfoil(flat_probes=True)  # every in-box XFoil design lacks a stall margin
    s = spec.model_copy(update={"max_evals": 14})
    final = run(s, start, run_id="r", runs_root=tmp_path, which="mock")
    d = tmp_path / "r"
    report = (d / "report.md").read_text()
    meta = json.loads((d / "meta.json").read_text())
    n = len(final["ledger"])
    # the mock's small steps near the box become near-duplicates, so it may declare a plateau first
    assert final["termination"] in ("eval_budget", "plateau") and f"Termination: **{final['termination']}**" in report
    assert f"Limits: evaluations {n} / 14" in report
    assert "## Best passing design\n\n**None.**" in report and "Best overall" not in report
    closest = next(r for r in final["ledger"] if r.params.cid == meta["closest_candidate_cid"])
    assert closest.verdict.status == "TARGET_MISS" and closest.result.fidelity == "xfoil"
    assert "## Closest candidate (did not pass)" in report and f"`{closest.params.cid}`" in report
    assert "  - stall_margin: d|Cl|/dα" in report and meta["closest_candidate_failing"][0].startswith("stall_margin")
    assert meta["best_passing_cid"] is None and meta["limits"]["evals"] == n
    probed = {r.params.cid for r in final["ledger"] if r.stall_margin is not None}
    assert probed and set(meta["viz"]["stall_plots"]) == probed
    for cid in probed:
        assert (d / f"stall_{cid}.png").stat().st_size > 1000 and f"(stall_{cid}.png)" in report


def test_report_with_a_pass_names_it(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    final = run(spec, start, run_id="p", runs_root=tmp_path, which="mock")
    d = tmp_path / "p"
    report = (d / "report.md").read_text()
    meta = json.loads((d / "meta.json").read_text())
    last = final["ledger"][-1]
    assert final["termination"] == "target_met" and meta["best_passing_cid"] == last.params.cid
    assert "## Best passing design\n\nA full PASS" in report and f"`{last.params.cid}`" in report
    assert "Closest candidate" not in report and meta["closest_candidate_cid"] is None


@pytest.mark.parametrize("key", ["best_cid", "best_xfoil_cid"])
def test_meta_drops_the_ambiguous_best_keys(spec, start, fake_xfoil, tmp_path, key):
    fake_xfoil()
    run(spec.model_copy(update={"max_evals": 2}), start, run_id=key, runs_root=tmp_path, which="mock")
    assert key not in json.loads((tmp_path / key / "meta.json").read_text())
