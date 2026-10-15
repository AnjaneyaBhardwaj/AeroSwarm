"""Milestone 2 evals, offline: recovery-ladder statistics and CAD sign scoring from the ledger, and the
XFoil failure zoo (fake solver; the committed cache evals/xfoil_zoo.json for the real results)."""

import json
from pathlib import Path

from swarm.evals import recovery, signs, zoo
from swarm.run import run
from swarm.state import CFDResult, Diagnosis, EvalRecord, StallMargin, Verdict, WingParams

ROOT = Path(__file__).parent.parent


def _p(**kw) -> WingParams:
    return WingParams(**({"main_camber": 0.06, "main_camber_pos": 0.4, "main_thickness": 0.13, "alpha_deg": 8.0} | kw))


def _rec(p, cl=-1.5, cd=0.017, fidelity="neuralfoil", level=None, fallback=None, signs_=None, parent=None, **kw):
    r = CFDResult(
        cid=p.cid,
        fidelity=fidelity,
        status=kw.pop("status", "converged"),
        cl=cl,
        cd=cd,
        solver_level=level,
        fallback_from=fallback,
    )
    v = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="NONE"), confidence=0.5)
    return EvalRecord(
        generation=0,
        params=p,
        result=r,
        verdict=v,
        rationale="",
        predicted_signs=signs_ or {},
        parent_cid=None if parent is None else getattr(parent, "params", parent).cid,
        **kw,
    )


# ------------------------------------------------------------------ recovery ladder


def test_ladder_stats_count_levels_fallbacks_and_probe_points():
    probe = StallMargin(
        alphas_deg=[8.0, 9.0, 10.0],
        cls=[-1.5, -1.58, None],
        levels=[2, 1, None],
        slopes=[0.08],
        threshold=0.05,
        ok=False,
    )
    ledger = [
        _rec(_p(), fidelity="neuralfoil"),  # not an XFoil solve
        _rec(_p(alpha_deg=9.0), fidelity="xfoil", level=0),
        _rec(_p(alpha_deg=10.0), fidelity="xfoil", level=2, stall_margin=probe),
        _rec(_p(alpha_deg=11.0), fidelity="neuralfoil", fallback="xfoil"),  # ladder exhausted
        _rec(_p(alpha_deg=12.0), fidelity="xfoil", level=0, status="not_converged", cl=None, cd=None),
    ]
    st = recovery.ladder_stats(ledger)
    d, pr = st["design"], st["probe"]
    assert d["solves"] == 4 and d["by_level"] == {0: 1, 1: 0, 2: 1, 3: 0}
    assert d["exhausted"] == 1 and d["unresolved"] == 1
    assert d["recovered"] == 1 and d["l0_failures"] == 2 and d["recovery_rate"] == 0.5
    assert pr["solves"] == 2 and pr["by_level"][1] == 1 and pr["exhausted"] == 1 and pr["recovery_rate"] == 0.5
    text = "\n".join(recovery.report_section(ledger))
    assert "## XFoil recovery ladder" in text and "| design point | 4 | 1 | 0 | 1 | 0 | 1 | 1 / 2 (50%) |" in text


def test_no_xfoil_solve_no_section():
    assert recovery.report_section([_rec(_p())]) == []


def test_run_report_counts_the_graph_ladder(spec, start, fake_xfoil, tmp_path):
    fake_xfoil(fail_levels=(0, 1))
    final = run(spec, start, run_id="lad", runs_root=tmp_path, which="mock")
    xf = [r for r in final["ledger"] if r.result.fidelity == "xfoil"]
    st = recovery.ladder_stats(final["ledger"])["design"]
    assert xf and st["by_level"][2] == len(xf) == st["recovered"] and st["exhausted"] == 0
    report = (tmp_path / "lad" / "report.md").read_text()
    assert "## XFoil recovery ladder" in report and f"{len(xf)} / {len(xf)} (100%)" in report


def test_run_report_counts_an_exhausted_ladder(spec, start, fake_xfoil, tmp_path):
    fake_xfoil(fail_levels=(0, 1, 2, 3))
    final = run(spec.model_copy(update={"max_evals": 8}), start, run_id="exh", runs_root=tmp_path, which="mock")
    st = recovery.ladder_stats(final["ledger"])["design"]
    fb = [r for r in final["ledger"] if r.result.fallback_from == "xfoil"]
    assert fb and st["exhausted"] == len(fb) and st["recovered"] == 0 and st["recovery_rate"] == 0.0


# ------------------------------------------------------------------ sign predictions


def test_joint_sign():
    assert signs.joint([-1, 0, -1]) == -1
    assert signs.joint([0, 0]) == 0
    assert signs.joint([1, -1]) is None


def test_sign_scoring_against_the_parent():
    base = _rec(_p(), cl=-1.50, cd=0.0170)
    ledger = [
        base,
        # more camber: more downforce (Cl more negative), more drag; both right
        _rec(_p(main_camber=0.07), cl=-1.56, cd=0.0175, signs_={"main_camber": (-1, 1)}, parent=base),
        # more alpha predicted to cost downforce: wrong on Cl; Cd change inside the deadband, predicted 0: right
        _rec(_p(alpha_deg=9.0), cl=-1.58, cd=0.01705, signs_={"alpha_deg": (1, 0)}, parent=base),
        # opposite Cl predictions: no joint Cl prediction; Cd agrees (+1) and is right
        _rec(
            _p(alpha_deg=9.0, main_thickness=0.14),
            cl=-1.55,
            cd=0.0180,
            signs_={"alpha_deg": (-1, 1), "main_thickness": (1, 1)},
            parent=base,
        ),
        # parent not in the ledger: not scored
        _rec(_p(alpha_deg=7.0), signs_={"alpha_deg": (1, -1)}, parent=_p(alpha_deg=1.0)),
        # parent only at another fidelity: not scored
        _rec(_p(main_camber=0.07), fidelity="xfoil", level=0, signs_={"main_camber": (-1, 1)}, parent=base),
    ]
    s = signs.score(ledger)
    assert s["records"] == 3 and s["no_parent"] == 2
    assert s["cl"] == {"n": 2, "correct": 1, "accuracy": 0.5} and s["cl_mixed"] == 1
    assert s["cd"]["n"] == 3 and s["cd"]["correct"] == 3
    a = s["params"]["alpha_deg"]
    assert a["changes"] == 2 and a["single"] == 1 and a["single_cl_correct"] == 0 and a["single_cd_correct"] == 1
    assert a["implied_dcl"] == {-1: 1, 0: 0, 1: 1}  # argued both ways
    text = "\n".join(signs.report_section(ledger))
    assert "Cl 1/2 (50%)" in text and "| alpha_deg | 2 | 0/1 | 1/1 | 1 / 0 / 1 |" in text


def test_quarantined_records_are_not_scored():
    base = _rec(_p())
    bad = _rec(_p(main_camber=0.07), cl=-1.6, signs_={"main_camber": (-1, 1)}, parent=base, quarantined=True)
    assert signs.score([base, bad])["records"] == 0 and signs.report_section([base, bad]) == []


def test_mock_run_report_scores_signs(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    run(spec, start, run_id="sg", runs_root=tmp_path, which="mock")
    assert "## CAD sign predictions" in (tmp_path / "sg" / "report.md").read_text()


# ------------------------------------------------------------------ failure zoo


def test_zoo_cases_are_deterministic_and_labelled():
    a, b = zoo.cases(), zoo.cases()
    assert [c["name"] for c in a] == [c["name"] for c in b]
    assert len({c["name"] for c in a}) == len(a) >= 50
    assert {c["category"] for c in a} == set(zoo.CATEGORIES)
    thin = [c for c in a if c["category"] == "thin_high_alpha"]
    assert thin and not any(zoo.fsae_legal(c["params"]) for c in thin)
    assert all(zoo.fsae_legal(c["params"]) for c in a if c["category"] == "fsae_high_alpha")


def _fake_solve(fail: set[int], cls: dict[int, float] | None = None):
    def solve(p, level):
        if level in fail:
            return CFDResult(
                cid=p.cid,
                fidelity="xfoil",
                status="not_converged",
                solver_level=level,
                failure_signature=f"not_converged@L{level}",
            )
        cl = (cls or {}).get(level, -1.5)
        return CFDResult(cid=p.cid, fidelity="xfoil", status="converged", cl=cl, cd=0.02, solver_level=level)

    return solve


def _ref(p):
    return CFDResult(cid=p.cid, fidelity="neuralfoil", status="converged", cl=-1.51, cd=0.019, confidence=0.9)


def test_zoo_outcomes_recovery_exhaustion_and_disagreement():
    c = zoo.cases()[0]
    clean = zoo.run_case(c, _fake_solve(set()), _ref)
    rec = zoo.run_case(c, _fake_solve({0, 1}), _ref)
    exh = zoo.run_case(c, _fake_solve({0, 1, 2, 3}), _ref)
    # L0 converges on another branch than the continuation levels: accepted, but it disagrees
    branch = zoo.run_case(c, _fake_solve(set(), {0: -1.34, 1: -1.34, 2: -1.48, 3: -1.52}), _ref)
    outs = [zoo.outcome(r) for r in (clean, rec, exh, branch)]
    assert [zoo.label(o) for o in outs] == ["clean", "recovered@L2", "exhausted", "clean + branch + panels"]
    assert outs[1]["first_signature"] == "not_converged@L0" and outs[1]["converged_levels"] == [2, 3]
    assert abs(outs[3]["branch_deviation"] - 0.14) < 1e-9 and abs(outs[3]["panel_deviation"] - 0.18) < 1e-9
    s = zoo.summarize([clean, rec, exh, branch])
    assert s["l0_failures"] == 2 and s["recovered"] == 1 and s["exhausted"] == 1 and s["branch"] == s["panels"] == 1
    assert [(x["attempts"], x["converged"]) for x in s["per_level"]] == [(4, 2), (2, 0), (2, 1), (1, 0)]
    md = zoo.markdown([clean, rec, exh, branch], {"date": "2026-10-15", "reynolds": 8.3e5, "ncrit": 9.0})
    assert "✗ not_converged@L0" in md and "recovered@L2" in md and "the ladder recovered 1 (50%)" in md


def test_committed_zoo_cache_is_consistent():
    data = json.loads((ROOT / "evals" / "xfoil_zoo.json").read_text())
    res = data["results"]
    assert [r["name"] for r in res] == [c["name"] for c in zoo.cases()]  # cache matches the case list
    assert all(len(r["levels"]) == 4 for r in res)
    s = zoo.summarize(res)
    by = s["by_category"].values()
    assert sum(c["cases"] for c in by) == s["cases"] == len(res)
    assert sum(c["clean"] + c["recovered"] + c["exhausted"] for c in by) == len(res)
    assert s["recovered"] + s["exhausted"] == s["l0_failures"]
    # the doc is regenerated from the cache (a hand-written "## Findings" section may follow)
    assert (ROOT / "docs" / "FAILURE_ZOO.md").read_text().startswith(zoo.markdown(res, data["meta"]))
