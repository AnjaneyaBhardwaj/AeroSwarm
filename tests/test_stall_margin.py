"""TE separation can never be target_met; a would-be-final design needs a stall margin.

Offline: fake solves, recorded XFoil numbers, NeuralFoil-backed fake XFoil.
`xfoil`-marked tests run the real binary on the session-2 near-stall PASS.
"""

import json
import math

import pytest
from conftest import good_stall

from swarm.agents.critic import review
from swarm.critic.numeric import VALIDATION, stall_check_required, suggest_diagnosis, validate
from swarm.critic.stall import measure_stall_margin
from swarm.run import run
from swarm.solvers import xfoil
from swarm.state import (
    BoundaryLayerSummary,
    CFDResult,
    DesignSpec,
    Diagnosis,
    Verdict,
    WingParams,
    speed_for_reynolds,
)

P = WingParams(main_camber=0.045, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=9.5)


def res(cl=-1.49, cd=0.0175, fidelity="xfoil", **kw):
    return CFDResult(cid=P.cid, fidelity=fidelity, status="converged", cl=cl, cd=cd, **{"solver_level": 0, **kw})


def probe_solver(cls_by_alpha, fail=(), log=None):
    """solve(alpha, level) over a Cl table; `fail` = levels that do not converge."""

    def solve(alpha, level):
        if log is not None:
            log.append((alpha, level))
        if level in fail:
            return CFDResult(cid=P.cid, fidelity="xfoil", status="not_converged", failure_signature=f"nc@L{level}")
        return res(cl=cls_by_alpha[alpha], solver_level=level)

    return solve


# ----------------------------------------------------------- TE separation


def sep_bl(xc=0.91):
    return BoundaryLayerSummary(cf_te=-2.5e-5, te_separation_xc=xc, source="xfoil_cf")


@pytest.mark.parametrize("fid", ["xfoil", "neuralfoil"])
def test_te_separation_in_the_target_box_is_target_miss(spec, fid):
    r = res(bl=sep_bl(), fidelity=fid, confidence=0.95)
    rep = validate(r, P, spec, [], stall=good_stall())  # even with a healthy margin
    assert rep.target_met and rep.ok and rep.suspect and not rep.terminal
    assert rep.status == "TARGET_MISS"
    assert not next(c for c in rep.checks if c.name == "te_separation").ok
    assert suggest_diagnosis(r, spec).symptom == "TE_SEPARATION_MAIN"


def test_reattaching_bubble_is_not_te_separation(spec):
    r = res(bl=BoundaryLayerSummary(cf_te=0.001, bubbles=[(0.3, 0.37)], source="xfoil_cf"))
    rep = validate(r, P, spec, [], stall=good_stall())
    assert rep.status == "PASS" and rep.terminal


def test_critic_cannot_relabel_te_separation(spec):
    class Liar:  # an LLM that calls the separated design a clean PASS
        def structured(self, role, system, user, schema, facts=None):
            return Verdict(status="PASS", diagnosis=Diagnosis(symptom="NONE"), confidence=0.9)

    r = res(bl=sep_bl())
    state = {
        "spec": spec,
        "result": r,
        "params": P,
        "numeric": validate(r, P, spec, [], stall=good_stall()),
        "ledger": [],
    }
    v = review(Liar(), state, None)
    assert v.status == "TARGET_MISS" and v.diagnosis.symptom == "TE_SEPARATION_MAIN"


# ----------------------------------------------------------- stall margin


def test_healthy_slope_passes_and_is_logged():
    sm = measure_stall_margin(res(cl=-1.5), 9.5, probe_solver({10.5: -1.59, 11.5: -1.68}))
    assert sm.ok and sm.failure is None
    assert sm.dcl_dalpha == pytest.approx(0.09) and sm.slopes == pytest.approx([0.09, 0.09])
    assert sm.alphas_deg == [9.5, 10.5, 11.5] and sm.cls == [-1.5, -1.59, -1.68] and sm.levels == [0, 0, 0]
    assert sm.threshold == VALIDATION.stall_min_dcl_dalpha


@pytest.mark.parametrize(
    "c1,c2",
    [(-1.52, -1.54), (-1.6, -1.55), (-1.5, -1.5), (-1.7, -1.72)],  # flat, rolls over, zero, stalls at +2
)
def test_flat_or_rolled_over_slope_fails(c1, c2):
    sm = measure_stall_margin(res(cl=-1.5), 9.5, probe_solver({10.5: c1, 11.5: c2}))
    assert not sm.ok and sm.failure is None and sm.dcl_dalpha < VALIDATION.stall_min_dcl_dalpha


def test_slope_at_threshold_passes_just_below_fails():
    thr = VALIDATION.stall_min_dcl_dalpha
    ok = measure_stall_margin(res(cl=-1.5), 9.5, probe_solver({10.5: -1.5 - thr, 11.5: -1.5 - 2 * thr}))
    bad = measure_stall_margin(res(cl=-1.5), 9.5, probe_solver({10.5: -1.5 - thr + 0.01, 11.5: -1.5 - 2 * thr}))
    assert ok.ok and not bad.ok


def test_te_separation_at_a_probe_fails_even_with_a_healthy_slope():
    seps = {10.5: 0.97}

    def solve(alpha, level):
        r = res(cl=-1.49 - 0.09 * (alpha - 9.5), solver_level=level)
        return r.model_copy(update={"bl": sep_bl(seps[alpha]) if alpha in seps else None})

    sm = measure_stall_margin(res(), 9.5, solve)
    assert sm.dcl_dalpha == pytest.approx(0.09) and not sm.ok
    assert sm.te_separation_xc == [None, 0.97, None] and sm.failure == "alpha+1: TE separation from x/c 0.97"
    seps.clear()
    assert measure_stall_margin(res(), 9.5, solve).ok


def test_probe_uses_the_ladder_each_level_once_then_gives_up():
    log = []
    sm = measure_stall_margin(res(cl=-1.5), 9.5, probe_solver({}, fail=(0, 1, 2, 3), log=log))
    assert [lvl for a, lvl in log if a == 10.5] == [0, 1, 2, 3]  # L0..L3, none repeated
    assert not sm.ok and sm.dcl_dalpha is None and "alpha+1" in sm.failure and "ladder exhausted" in sm.failure


def test_probe_recovers_at_a_higher_ladder_level():
    log = []
    sm = measure_stall_margin(res(cl=-1.5), 9.5, probe_solver({10.5: -1.59, 11.5: -1.68}, fail=(0,), log=log))
    assert sm.ok and sm.levels == [0, 1, 1]
    assert [lvl for a, lvl in log] == [0, 1, 0, 1]


def test_nonfinite_probe_is_not_a_margin():
    def solve(alpha, level):
        return res(cl=math.nan if alpha > 10 else -1.6, solver_level=level)

    sm = measure_stall_margin(res(cl=-1.5), 9.5, solve)
    assert not sm.ok and sm.dcl_dalpha is None


def test_stall_margin_gates_target_met(spec):
    clean = validate(res(), P, spec, [])
    assert clean.target_met and not clean.terminal and clean.status == "TARGET_MISS"  # probe not run yet
    assert stall_check_required(res(), clean)
    assert validate(res(), P, spec, [], stall=good_stall()).terminal
    bad = good_stall(slope=0.02).model_copy(update={"ok": False})
    rep = validate(res(), P, spec, [], stall=bad)
    assert rep.target_met and not rep.terminal and rep.status == "TARGET_MISS"
    chk = next(c for c in rep.checks if c.name == "stall_margin")
    assert not chk.ok and chk.value == pytest.approx(0.02)


def test_probe_only_runs_for_a_candidate_that_would_otherwise_end_the_run(spec):
    assert not stall_check_required(None, validate(None, P, spec, []))
    for r in (res(cl=-1.2), res(bl=sep_bl()), res(fidelity="neuralfoil", confidence=0.95)):
        assert not stall_check_required(r, validate(r, P, spec, []))
    fb = res(fidelity="neuralfoil", confidence=0.95, fallback_from="xfoil")
    assert not stall_check_required(fb, validate(fb, P, spec, []))


def test_neuralfoil_screening_pass_needs_no_probe(spec):
    rep = validate(res(fidelity="neuralfoil", confidence=0.95), P, spec, [])
    assert rep.status == "PASS" and not rep.terminal
    assert all(c.name != "stall_margin" for c in rep.checks)


# ----------------------------------------------------------- graph


def test_graph_logs_margin_in_the_ledger_row(spec, start, fake_xfoil, tmp_path):
    calls = fake_xfoil()
    final = run(spec, start, run_id="m", runs_root=tmp_path, which="mock")
    assert final["termination"] == "target_met"
    last = final["ledger"][-1]
    assert last.verdict.status == "PASS" and last.stall_margin.ok
    assert last.stall_margin.alphas_deg == pytest.approx([last.params.alpha_deg + d for d in (0, 1, 2)])
    assert sum(1 for c in calls if len(c) == 3) == 2  # one probe pair, only for the final candidate
    row = json.loads((tmp_path / "m" / "ledger.jsonl").read_text().splitlines()[-1])
    assert row["stall_margin"]["ok"] and row["stall_margin"]["dcl_dalpha"] >= VALIDATION.stall_min_dcl_dalpha
    events = [json.loads(x) for x in (tmp_path / "m" / "events.jsonl").read_text().splitlines()]
    assert [e["cid"] for e in events if e.get("event") == "stall_margin"] == [last.params.cid]
    assert "stall d" in (tmp_path / "m" / "report.md").read_text()


def test_graph_never_ends_on_a_design_without_margin(spec, start, fake_xfoil, tmp_path):
    fake_xfoil(flat_probes=True)
    s = spec.model_copy(update={"max_evals": 14})
    final = run(s, start, run_id="f", runs_root=tmp_path, which="mock")
    assert final["termination"] != "target_met"
    from swarm.critic.numeric import in_target

    in_box = [r for r in final["ledger"] if r.result.fidelity == "xfoil" and in_target(r.result, s)]
    assert in_box, "the run should have reached the box at xfoil"
    for r in in_box:
        assert r.verdict.status == "TARGET_MISS" and r.stall_margin is not None and not r.stall_margin.ok


# ------------------------------------------------- regression: session 2's final design

# Session 2's hard preset (before the near-stall fix): Cl -2.00 ± 0.03, Cd <= 0.030, Re 3e5.
OLD_HARD = DesignSpec(
    component="wing_1el",
    target_cl=-2.00,
    cl_tol=0.03,
    cd_max=0.030,
    speed_mps=round(speed_for_reynolds(3.0e5, 300.0), 2),
    max_evals=30,
    max_wall_hours=0.5,
    rulebook="FS2026_v1.1",  # session 2 ran under the Formula Student rulebook (t 0.1085 is FSAE-illegal)
)
# 3df51198b3, the design that session 2 ended on with PASS / target_met.
SESSION2_FINAL = WingParams(main_camber=0.09, main_camber_pos=0.3709, main_thickness=0.1085, alpha_deg=11.6191)


def test_session2_final_design_id():
    assert SESSION2_FINAL.cid == "3df51198b3"


def test_session2_final_design_is_rejected_recorded_result():
    """XFoil 6.99 result as recorded in session 2 (L0 fails, L1 converges)."""
    r = CFDResult(
        cid=SESSION2_FINAL.cid,
        fidelity="xfoil",
        status="converged",
        cl=-1.9758,
        cd=0.02869,
        cm=0.1668,
        solver_level=1,
        bl=BoundaryLayerSummary(
            cf_te=-2.5e-5,
            te_separation_xc=0.91189,
            bubbles=[(0.32833, 0.37301)],
            transition_xc=0.3642,
            source="xfoil_cf",
        ),
    )
    rep = validate(r, SESSION2_FINAL, OLD_HARD, [], stall=good_stall())
    assert rep.target_met  # still inside the old box, which is the point
    assert rep.status == "TARGET_MISS" and not rep.terminal
    assert [c.name for c in rep.checks if not c.ok] == ["te_separation"]
    assert suggest_diagnosis(r, OLD_HARD).symptom == "TE_SEPARATION_MAIN"


@pytest.mark.xfoil
@pytest.mark.skipif(not xfoil.xfoil_available(), reason="xfoil binary not installed")
def test_session2_final_design_is_rejected_by_real_xfoil(tmp_path):
    from swarm.cad.build import build

    geo = build(SESSION2_FINAL, OLD_HARD, tmp_path)
    assert not geo.violations
    r = None
    for lvl in range(xfoil.MAX_LEVEL + 1):  # the same ladder the graph walks
        r = xfoil.evaluate(SESSION2_FINAL, OLD_HARD, geo.coords_path, tmp_path, lvl)
        if r.status == "converged":
            break
    assert r.status == "converged" and r.cl == pytest.approx(-1.9758, abs=2e-3)
    assert r.bl.te_separation_xc == pytest.approx(0.912, abs=0.01) and r.bl.cf_te < 0
    rep = validate(r, SESSION2_FINAL, OLD_HARD, [])
    assert rep.target_met and not rep.terminal and rep.status == "TARGET_MISS"
    assert not next(c for c in rep.checks if c.name == "te_separation").ok
    assert not stall_check_required(r, rep)  # separated: no probe needed, none run


@pytest.mark.xfoil
@pytest.mark.skipif(not xfoil.xfoil_available(), reason="xfoil binary not installed")
def test_real_xfoil_probe_rejects_a_design_that_rolls_over_one_degree_later(tmp_path):
    """In the session-3 hard box (Cl -1.78 ± 0.03, Cd <= 0.020) and attached at its design alpha,
    but at alpha+1 the TE separates and Cl peaks before alpha+2 (found by the mock then)."""
    from swarm.cad.build import build
    from swarm.run import HARD_SPEC as CURRENT

    HARD_SPEC = CURRENT.model_copy(update={"target_cl": -1.78, "cd_max": 0.020})

    p = WingParams(main_camber=0.0774, main_camber_pos=0.3892, main_thickness=0.1041, alpha_deg=9.1553)
    geo = build(p, HARD_SPEC, tmp_path)

    def solve(alpha, lvl):
        return xfoil.evaluate(p, HARD_SPEC, geo.coords_path, tmp_path, lvl, alpha_deg=alpha)

    base = None
    for lvl in range(xfoil.MAX_LEVEL + 1):
        base = solve(p.alpha_deg, lvl)
        if base.status == "converged":
            break
    rep0 = validate(base, p, HARD_SPEC, [])
    assert rep0.target_met and stall_check_required(base, rep0)
    sm = measure_stall_margin(base, p.alpha_deg, solve)
    rep = validate(base, p, HARD_SPEC, [], stall=sm)
    assert not sm.ok and sm.dcl_dalpha < VALIDATION.stall_min_dcl_dalpha
    assert rep.target_met and rep.status == "TARGET_MISS" and not rep.terminal
