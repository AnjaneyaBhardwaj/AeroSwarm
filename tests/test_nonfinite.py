"""Non-finite guard. Our XFoil build has FP traps off, so a blown-up solve can
print NaN / Infinity / `****` instead of aborting. The parser drops those rows,
the wrapper labels the failure, and the numeric Critic rejects any NaN/inf
that reaches it (Cl, Cd, Cm, Cf-derived BL facts) as NUMERICAL_FAILURE."""

import json
import math
import subprocess

import pytest
from conftest import FIXTURES

from swarm.cad.build import build
from swarm.critic.numeric import nonfinite_fields, suggest_diagnosis, validate
from swarm.ledger import best_record, objective, usable
from swarm.run import run
from swarm.solvers import neuralfoil, xfoil
from swarm.state import BoundaryLayerSummary, CFDResult, EvalRecord, WingParams

NAN, INF = float("nan"), float("inf")
P = WingParams(main_camber=0.045, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=9.5)
POLAR_HEAD = "header\n  alpha    CL        CD       CDp       CM     Top_Xtr  Bot_Xtr\n ------ -------- ---------\n"


def res(**kw):
    base = {"cid": P.cid, "fidelity": "xfoil", "status": "converged", "cl": -1.49, "cd": 0.0175, "cm": 0.1}
    return CFDResult(**{**base, **kw})


# ------------------------------------------------------------------ parser


@pytest.mark.parametrize(
    "row",
    [
        "   4.000      NaN   0.00755   0.00129  -0.0550   0.4153   0.9997",
        "   4.000   0.7065       NaN   0.00129  -0.0550   0.4153   0.9997",
        "   4.000   0.7065   0.00755   0.00129      NaN   0.4153   0.9997",
        "   4.000   0.7065  Infinity   0.00129  -0.0550   0.4153   0.9997",
        "   4.000 -Infinity  0.00755   0.00129  -0.0550   0.4153   0.9997",
        "   4.000 ********   0.00755   0.00129  -0.0550   0.4153   0.9997",  # Fortran overflow field
        "   4.000   0.7065   0.00755   0.00129     -inf   0.4153   0.9997",
    ],
)
def test_parse_polar_drops_nonfinite_rows(row):
    txt = POLAR_HEAD + row + "\n   5.000   0.8000   0.00800   0.00150  -0.0560   0.4000   0.9990\n"
    rows = xfoil.parse_polar(txt)
    assert [r["alpha"] for r in rows] == [5.0]
    raw = xfoil.parse_polar(txt, finite_only=False)
    assert [r["alpha"] for r in raw] == [4.0, 5.0]
    assert not all(math.isfinite(v) for v in raw[0].values())


def test_parse_polar_fixture_still_finite():
    rows = xfoil.parse_polar((FIXTURES / "xfoil_polar_sep13.txt").read_text())
    assert len(rows) == 1 and all(math.isfinite(v) for v in rows[0].values())


def _poison_dump(col: int, token: str) -> str:
    """Recorded dump with one surface station's column `col` replaced by `token`."""
    lines = (FIXTURES / "xfoil_dump_sep13.txt").read_text().splitlines()
    i = next(k for k, line in enumerate(lines) if line.strip() and not line.lstrip().startswith("#")) + 20
    parts = lines[i].split()
    parts[col] = token
    lines[i] = "  ".join(parts)
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "*********"])
def test_parse_dump_rejects_nonfinite_cf(token):
    with pytest.raises(xfoil.NonFiniteDump):
        xfoil.parse_dump(_poison_dump(6, token))


def test_parse_dump_rejects_nonfinite_x():
    with pytest.raises(xfoil.NonFiniteDump):
        xfoil.parse_dump(_poison_dump(1, "NaN"))


def test_summarize_bl_records_te_cf():
    d = xfoil.parse_dump((FIXTURES / "xfoil_dump_sep13.txt").read_text())
    bl = xfoil.summarize_bl(d, upright_cl=1.6951, transition={})
    assert bl.cf_te is not None and bl.cf_te < 0  # separated at the TE


# ------------------------------------------------------------------ wrapper


def _exec_writing(polar: str, dump: str):
    def _exec(argv, script, cwd, timeout):
        (cwd / xfoil.POLAR).write_text(polar)
        (cwd / xfoil.DUMP).write_text(dump)
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    return _exec


def _sep13_polar(cl_token: str | None = None) -> str:
    text = (FIXTURES / "xfoil_polar_sep13.txt").read_text()
    if cl_token is None:
        return text
    lines = text.splitlines()
    parts = lines[-1].split()
    parts[1] = cl_token
    return "\n".join(lines[:-1] + ["   " + "   ".join(parts)]) + "\n"


SEP = WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.12, alpha_deg=13.0)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "********"])
def test_wrapper_labels_nonfinite_coefficients(spec, tmp_path, monkeypatch, token):
    monkeypatch.setenv("XFOIL_BIN", "/bin/true")
    dump = (FIXTURES / "xfoil_dump_sep13.txt").read_text()
    monkeypatch.setattr(xfoil, "_exec", _exec_writing(_sep13_polar(token), dump))
    geo = build(SEP, spec, tmp_path)
    r = xfoil.evaluate(SEP, spec, geo.coords_path, tmp_path, 0)
    assert r.status == "not_converged" and r.cl is None
    assert r.failure_signature == "nonfinite_coeffs@L0"


def test_wrapper_labels_nonfinite_cf(spec, tmp_path, monkeypatch):
    monkeypatch.setenv("XFOIL_BIN", "/bin/true")
    monkeypatch.setattr(xfoil, "_exec", _exec_writing(_sep13_polar(), _poison_dump(6, "NaN")))
    geo = build(SEP, spec, tmp_path)
    r = xfoil.evaluate(SEP, spec, geo.coords_path, tmp_path, 1)
    assert r.status == "not_converged" and r.failure_signature == "nonfinite_cf@L1"


def test_wrapper_finite_output_unchanged(spec, tmp_path, monkeypatch):
    monkeypatch.setenv("XFOIL_BIN", "/bin/true")
    dump = (FIXTURES / "xfoil_dump_sep13.txt").read_text()
    monkeypatch.setattr(xfoil, "_exec", _exec_writing(_sep13_polar(), dump))
    geo = build(SEP, spec, tmp_path)
    r = xfoil.evaluate(SEP, spec, geo.coords_path, tmp_path, 0)
    assert r.status == "converged" and r.cl == -1.6951 and r.bl.cf_te < 0


# ------------------------------------------------------------------ numeric Critic


@pytest.mark.parametrize(
    "kw,field",
    [
        ({"cl": NAN}, "cl"),
        ({"cl": -INF}, "cl"),
        ({"cd": NAN}, "cd"),
        ({"cd": INF}, "cd"),
        ({"cm": NAN}, "cm"),
        ({"cm": INF}, "cm"),
        ({"bl": BoundaryLayerSummary(cf_te=NAN, source="xfoil_cf")}, "cf_te"),
        ({"bl": BoundaryLayerSummary(cf_te=-INF, source="xfoil_cf")}, "cf_te"),
        ({"bl": BoundaryLayerSummary(te_separation_xc=NAN, source="xfoil_cf")}, "te_separation_xc"),
        ({"bl": BoundaryLayerSummary(bubbles=[(0.1, NAN)], source="xfoil_cf")}, "bubble[0]"),
    ],
)
def test_critic_rejects_nonfinite(spec, kw, field):
    r = res(**kw)
    assert nonfinite_fields(r) == [field]
    rep = validate(r, P, spec, [])
    assert rep.failure_class == "NUMERICAL_FAILURE" and rep.status == "NUMERICAL_FAILURE"
    assert not rep.target_met and not rep.terminal
    finite = next(c for c in rep.checks if c.name == "finite")
    assert not finite.ok and field in finite.value
    # nothing downstream ran on garbage: no NON_PHYSICAL misclassification
    assert [c.name for c in rep.checks] == ["convergence", "finite"]


def test_critic_rejects_nonfinite_at_neuralfoil_too(spec):
    rep = validate(res(fidelity="neuralfoil", confidence=0.9, cd=NAN), P, spec, [])
    assert rep.failure_class == "NUMERICAL_FAILURE"


def test_finite_result_passes_finite_check(spec):
    rep = validate(res(bl=BoundaryLayerSummary(cf_te=0.001, source="xfoil_cf")), P, spec, [])
    assert rep.status == "PASS" and next(c for c in rep.checks if c.name == "finite").ok


def test_nonfinite_rows_never_become_best(spec):
    bad = EvalRecord(generation=0, params=P, verdict=None, rationale="", result=res(cl=NAN))
    good = EvalRecord(generation=0, params=P, verdict=None, rationale="", result=res(cl=-1.2))
    assert not usable(bad) and objective(bad.result, spec) == INF
    assert best_record([bad, good], spec) is good
    # a NaN on another tier must not poison the fidelity-gap check
    assert validate(res(), P, spec, [bad]).status == "PASS"
    assert suggest_diagnosis(res(cd=INF), spec).symptom == "NONE"


# ------------------------------------------------------------------ graph


def test_graph_recovers_from_nonfinite_xfoil(spec, start, tmp_path, monkeypatch):
    """L0 returns NaN coefficients (as if parsed past the guard); the Critic sends it
    to the ladder, L1 is finite, and the NaN never reaches the ledger as a result."""
    calls = []

    def evaluate(params, spec, coords_path, run_dir, level):
        calls.append((params.cid, level))
        r = neuralfoil.evaluate(params, spec)
        r = r.model_copy(update={"fidelity": "xfoil", "solver_level": level, "confidence": None})
        return r.model_copy(update={"cl": NAN}) if level == 0 else r

    monkeypatch.setattr("swarm.solvers.xfoil.evaluate", evaluate)
    final = run(spec, start, run_id="nf", runs_root=tmp_path, which="mock")
    events = [json.loads(x) for x in (tmp_path / "nf" / "events.jsonl").read_text().splitlines()]
    nv = [e for e in events if e.get("node") == "numeric_validate" and "finite" in e.get("failed", [])]
    assert nv and all(e["status"] == "NUMERICAL_FAILURE" for e in nv)
    assert any(e.get("event") == "xfoil_recovery" and e["from_level"] == 0 for e in events)
    xf = [r for r in final["ledger"] if r.result.fidelity == "xfoil"]
    assert xf and all(math.isfinite(r.result.cl) and r.result.solver_level >= 1 for r in xf)
    assert final["termination"] == "target_met"
