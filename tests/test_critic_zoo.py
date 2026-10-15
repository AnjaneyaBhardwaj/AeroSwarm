"""Critic failure zoo (milestone 3), offline: the committed cases, the numeric arm, and the LLM arms through a
scripted client (images reach the vision arm only; a fatal finding is a hard flag)."""

import json
import sys
from pathlib import Path

from swarm.critic.render import IMAGES
from swarm.evals import critic_zoo as cz
from swarm.llm.client import ScriptedClient
from swarm.state import Diagnosis, Finding, Verdict

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import critic_eval  # noqa: E402

SPEC = critic_eval.SPEC


def _cases() -> tuple[dict, list[dict]]:
    data = json.loads((ROOT / "evals" / "critic_zoo.json").read_text())
    return data["meta"], data["cases"]


def test_committed_cases_are_labelled_and_complete():
    _, raw = _cases()
    assert len(raw) >= 25 and len({c["name"] for c in raw}) == len(raw)
    for c in raw:
        assert c["kind"] in cz.KINDS and c["label"] == cz.KINDS[c["kind"]][0]
        assert c["result"]["status"] == "converged" and c["surface"]["suction"]["x"]
    labels = [c["label"] for c in raw]
    assert labels.count("trust") >= 10 and labels.count("flag") >= 12


def test_numeric_arm_is_deterministic_and_matches_the_committed_results():
    _, raw = _cases()
    rows = cz.run_arm([cz.load_case(c) for c in raw], SPEC, "numeric", log=lambda *_: None)
    committed = json.loads((ROOT / "evals" / "critic_results_numeric.json").read_text())
    assert rows == committed
    by = {r["name"]: r for r in rows}
    assert by["sign_flip_0"]["hard"] and by["drag_reference_0"]["hard"]
    assert not any(r["hard"] for r in rows if r["label"] == "trust")
    assert by["wrong_branch_0"]["soft"] and not by["wrong_branch_0"]["hard"]  # fidelity gap: a doubt only


def _verdict(fatal: bool) -> Verdict:
    f = Finding(
        observation="Cp area too small for the printed Cl",
        location="x/c 0-1",
        source="cp",
        consistent_with_numeric=False,
        severity="fatal" if fatal else "info",
    )
    return Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="NONE"), findings=[f], confidence=0.7)


def test_llm_arms_send_images_only_with_vision(tmp_path):
    _, raw = _cases()
    cases = [cz.load_case(c) for c in raw if c["name"] in ("clean_xfoil_0", "coarse_panels_0")]
    text = ScriptedClient([_verdict(False), _verdict(False)])
    rows_t = cz.run_arm(cases, SPEC, "llm_text", text, tmp_path, log=lambda *_: None)
    assert all(c["images"] == {} for c in text.calls) and "No images" in text.calls[0]["system"]
    vis = ScriptedClient([_verdict(False), _verdict(True)])
    rows_v = cz.run_arm(cases, SPEC, "llm_vision", vis, tmp_path, log=lambda *_: None)
    assert all(sorted(c["images"]) == sorted(IMAGES) for c in vis.calls)
    assert all(Path(p).exists() for c in vis.calls for p in c["images"].values())
    assert [r["hard"] for r in rows_t] == [False, False]
    assert [r["hard"] for r in rows_v] == [False, True] and rows_v[1]["status"] == "NON_PHYSICAL"
    s = cz.score(rows_v)
    assert s["tp"] == 1 and s["fp"] == 0 and s["precision"] == 1.0 and s["recall"] == 1.0


def test_an_llm_error_is_recorded_not_scored(tmp_path):
    _, raw = _cases()
    cases = [cz.load_case(raw[0])]
    rows = cz.run_arm(cases, SPEC, "llm_text", ScriptedClient([]), tmp_path, log=lambda *_: None)
    assert "error" in rows[0] and "hard" not in rows[0]


def test_score_and_markdown():
    rows = [
        {"name": "a", "kind": "sign_flip", "label": "flag", "hard": True, "soft": True, "status": "NON_PHYSICAL"},
        {"name": "b", "kind": "coarse_panels", "label": "flag", "hard": False, "soft": True, "status": "TARGET_MISS"},
        {"name": "c", "kind": "clean_xfoil", "label": "trust", "hard": True, "soft": True, "status": "NON_PHYSICAL"},
    ]
    s = cz.score(rows)
    assert (s["tp"], s["fp"], s["fn"]) == (1, 1, 1) and s["precision"] == 0.5 and s["recall"] == 0.5
    assert cz.score(rows, "soft")["recall"] == 1.0
    cases = [{"name": r["name"], "kind": r["kind"], "label": r["label"]} for r in rows]
    md = cz.markdown(cases, {"numeric": rows}, {"built": "2026-10-15"})
    assert "| numeric | 3 | 0 | 50% (1/2) | 50% (1/2) |" in md and "| llm_vision | not run |" in md


def test_committed_doc_is_regenerated_from_the_cache():
    meta, raw = _cases()
    results = {
        a: json.loads(p.read_text()) for a in cz.ARMS if (p := ROOT / "evals" / f"critic_results_{a}.json").exists()
    }
    assert (ROOT / "docs" / "CRITIC_EVAL.md").read_text().startswith(cz.markdown(raw, results, meta))
