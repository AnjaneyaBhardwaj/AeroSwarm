"""Viewer export (swarm/viz/export.py): numbers from the ledger, text verbatim from the traces."""

import json
from pathlib import Path

import pytest

from swarm.baselines import search
from swarm.ledger import RunFiles
from swarm.run import HARD_SPEC
from swarm.state import WingParams
from swarm.viz.export import OUTLINE_POINTS, export_run, summarise_baseline, trim, write_index

EXAMPLE = Path("runs/examples/hard_llm_20261001-201455-faf6a3")


@pytest.fixture(scope="module")
def exported():
    return export_run(EXAMPLE, name="example")


def _traces(role):
    return [
        json.loads(line)["output"]
        for line in (EXAMPLE / "traces.jsonl").read_text().splitlines()
        if json.loads(line).get("role") == role and json.loads(line).get("type") == "llm_call"
    ]


def _verbatim(short: str, full: str) -> bool:
    return short == full or (short.endswith(" …") and full.startswith(short[:-2]))


def test_trim_is_a_verbatim_prefix():
    text = "word " * 100
    out = trim(text, 50)
    assert out.endswith(" …") and text.startswith(out[:-2]) and len(out) <= 52
    assert trim("short", 50) == "short"
    assert trim(None, 10) == ""


def test_generations_and_numbers_match_the_ledger(exported):
    ledger = RunFiles(EXAMPLE).read_ledger()
    gens = exported["generations"]
    assert [g["gen"] for g in gens] == sorted({r.generation for r in ledger})
    flat = [e for g in gens for e in g["evals"]]
    assert len(flat) == len(ledger) == exported["evals"]
    for e, r in zip(flat, ledger, strict=True):
        assert e["cid"] == r.params.cid
        assert e["cl"] == pytest.approx(r.result.cl, abs=1e-6)
        assert e["cd"] == pytest.approx(r.result.cd, abs=1e-6)
        assert e["solver"] == r.result.fidelity
        assert e["verdict"] == r.verdict.status
    o = exported["outcome"]
    assert o["result"] == "target_met" and o["cid"] == "abb9803ead" and o["solver"] == "xfoil"
    assert o["evals_to_target"] == 23


def test_agent_text_is_verbatim_from_traces(exported):
    gens = exported["generations"]
    hyps = [t["hypothesis"] for t in _traces("chief")]
    assert len(hyps) == len(gens)
    for g, h in zip(gens, hyps, strict=True):
        assert _verbatim(g["chief"]["hypothesis"], h)
    mechs = {c["mechanism"] for t in _traces("cad") for c in t["changes"]}
    cad = [c for g in gens for a in g["cad"] for c in a["changes"]]
    assert len(cad) == sum(len(t["changes"]) for t in _traces("cad"))
    assert all(any(_verbatim(c["mechanism"], m) for m in mechs) for c in cad)
    evidence = {x for t in _traces("critic") for x in t["diagnosis"]["evidence"]}
    assert all(g["critic_source"] == "llm" for g in gens)
    assert all(any(_verbatim(x, e) for e in evidence) for g in gens for x in g["critic"]["evidence"])


def test_cad_attempt_outcomes_and_overrides(exported):
    g1 = exported["generations"][1]
    assert [a["outcome"] for a in g1["cad"]] == ["rejected", "accepted"]
    assert "LE radius" in g1["cad"][0]["rejection"]
    overrides = [c for g in exported["generations"] for a in g["cad"] for c in a["changes"] if c["override_reason"]]
    assert overrides, "the example run has CAD overrides of the Chief"
    assert any(a.get("disagreements") for g in exported["generations"] for a in g["cad"])


def test_outlines_cover_every_candidate(exported):
    cids = {e["cid"] for g in exported["generations"] for e in g["evals"]} | {exported["start_cid"]}
    assert cids <= set(exported["outlines"])
    for ol in exported["outlines"].values():
        assert len(ol) == 2 * OUTLINE_POINTS - 1
    # race-car orientation: the inverted section's TE is raised by alpha
    start = exported["outlines"][exported["start_cid"]]
    assert start[0][1] > 0.1


def test_index_and_baseline(tmp_path, exported):
    spec = HARD_SPEC.model_copy(update={"max_evals": 3})
    start = WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=6.0)
    search("optuna", spec, start, 0, tmp_path / "opt", write_report=False)
    b = summarise_baseline(tmp_path / "opt")
    assert b["method"] == "optuna" and b["evals"] == 3 and b["result"] in ("no_pass", "target_met", "passed")
    out = tmp_path / "runs"
    out.mkdir()
    (out / "a.json").write_text(json.dumps({**exported, "baseline": b}))
    idx = write_index(out)
    assert [r["file"] for r in idx["runs"]] == ["a.json"]
    assert idx["runs"][0]["start"] == exported["start"]
    assert json.loads((out / "index.json").read_text()) == json.loads(json.dumps(idx))
