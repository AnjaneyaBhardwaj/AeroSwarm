"""Vision Critic (milestone 3), offline: deterministic rendering, images in the LLM request and trace, graph
wiring (rendered only for a client that sees images, and only with vision on; off by default), the vision
veto/no-rescue rule, and the deterministic surface checks (Cp integral, Cp spike)."""

import base64
import json
from pathlib import Path

import numpy as np
from test_llm import FakeSDK

from swarm.agents.critic import merge_verdict
from swarm.briefs import image_text
from swarm.critic.numeric import validate
from swarm.critic.render import IMAGES, render, surface_data
from swarm.llm.client import AnthropicClient, TraceLogger
from swarm.llm.mock import MockClient
from swarm.run import run
from swarm.solvers import neuralfoil
from swarm.state import CFDResult, Diagnosis, Finding, Verdict, WingParams

FIX = Path(__file__).parent / "fixtures"
P = WingParams(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=4.0)
PNG = b"\x89PNG\r\n\x1a\n"


def _xfoil_result(p=P) -> CFDResult:
    return CFDResult(
        cid=p.cid,
        fidelity="xfoil",
        status="converged",
        cl=-0.95,
        cd=0.012,
        solver_level=0,
        artifacts={"bl_dump": str(FIX / "xfoil_dump_att4.txt")},
    )


def test_xfoil_surface_from_the_dump():
    d = surface_data(P, None, _xfoil_result())
    s, p = d["suction"], d["pressure"]
    assert set(s) == {"x", "cp", "h", "cf"} and len(s["x"]) > 50
    assert s["x"][0] < 0.01 and s["x"][-1] > 0.99  # LE -> TE
    assert np.max(-s["cp"]) > np.max(-p["cp"])  # the suction side carries the suction peak


def test_neuralfoil_surface_and_render(spec, tmp_path):
    r = neuralfoil.evaluate(P, spec)
    d = surface_data(P, spec, r)
    assert len(d["suction"]["x"]) == 32 and "cf" not in d["suction"]
    parent = WingParams(main_camber=0.05, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=4.0)
    out = render(P, r, spec, tmp_path, parent=(parent, neuralfoil.evaluate(parent, spec)))
    assert sorted(out) == sorted(IMAGES)
    for path in out.values():
        assert Path(path).read_bytes()[:8] == PNG and Path(path).stat().st_size > 5000


def test_render_is_deterministic_and_takes_injected_surfaces(spec, tmp_path):
    r = neuralfoil.evaluate(P, spec)
    a = render(P, r, spec, tmp_path / "a")
    b = render(P, r, spec, tmp_path / "b")
    assert all(Path(a[k]).read_bytes() == Path(b[k]).read_bytes() for k in IMAGES)
    d = surface_data(P, spec, r)
    kinked = {**d, "suction": {**d["suction"], "cp": d["suction"]["cp"] - 1.5 * (abs(d["suction"]["x"] - 0.5) < 0.04)}}
    c = render(P, r, spec, tmp_path / "c", surface=kinked)
    assert Path(c["cp"]).read_bytes() != Path(a["cp"]).read_bytes()


def test_render_without_a_result(spec, tmp_path):
    bad = CFDResult(cid=P.cid, fidelity="xfoil", status="not_converged")
    out = render(P, bad, spec, tmp_path)
    assert all(Path(v).exists() for v in out.values())


def test_anthropic_request_carries_labelled_images_and_the_trace_only_paths(spec, tmp_path):
    imgs = render(P, neuralfoil.evaluate(P, spec), spec, tmp_path / "img")
    v = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="NONE"), confidence=0.6)
    sdk = FakeSDK(v)
    trace = TraceLogger(tmp_path / "traces.jsonl")
    AnthropicClient(trace, sdk_client=sdk).structured("critic", "sys", "numbers", Verdict, images=imgs)
    content = sdk.requests[0]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "numbers"}
    kinds = [b["type"] for b in content[1:]]
    assert kinds == ["text", "image"] * len(IMAGES)
    assert [b["text"] for b in content[1::2]] == [f"Image `{k}`:" for k in imgs]
    img = content[2]["source"]
    assert img["media_type"] == "image/png" and base64.b64decode(img["data"])[:8] == PNG
    rec = json.loads((tmp_path / "traces.jsonl").read_text().splitlines()[0])
    assert set(rec["images"]) == set(IMAGES) and "data" not in json.dumps(rec["images"])
    assert all(len(x["sha1"]) == 12 for x in rec["images"].values())


def test_without_images_the_request_is_plain_text(spec, tmp_path):
    sdk = FakeSDK(Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="NONE"), confidence=0.6))
    AnthropicClient(TraceLogger(None), sdk_client=sdk).structured("critic", "s", "u", Verdict)
    assert sdk.requests[0]["messages"][0]["content"] == "u"


class SeeingMock(MockClient):
    """The rule-based mock, but declared image-capable so the graph renders and sends images (tests only)."""

    sees_images = True


def _critic_calls(d: Path) -> list[dict]:
    return [
        json.loads(x) for x in (d / "traces.jsonl").read_text().splitlines() if '"llm_call"' in x and '"critic"' in x
    ]


def test_graph_sends_images_to_a_seeing_critic(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    d = tmp_path / "v"
    llm = SeeingMock(TraceLogger(d / "traces.jsonl"))
    final = run(spec.model_copy(update={"max_evals": 6}), start, run_id="v", runs_root=tmp_path, llm=llm, vision=True)
    recs = [r for r in final["ledger"] if r.critic_images]
    assert recs and all(sorted(r.critic_images) == sorted(IMAGES) for r in recs)
    assert all(Path(p).exists() for r in recs for p in r.critic_images.values())
    calls = _critic_calls(d)
    assert calls and all(set(c["images"]) == set(IMAGES) for c in calls)
    assert "You also receive images" in calls[0]["system"] and "## Images" in calls[0]["user"]
    assert json.loads((d / "meta.json").read_text())["vision"] is True


def test_no_vision_and_the_plain_mock_render_nothing(spec, start, fake_xfoil, tmp_path):
    fake_xfoil()
    d = tmp_path / "nv"
    llm = SeeingMock(TraceLogger(d / "traces.jsonl"))
    final = run(
        spec.model_copy(update={"max_evals": 4}), start, run_id="nv", runs_root=tmp_path, llm=llm
    )  # default: off
    assert not any(r.critic_images for r in final["ledger"])
    calls = _critic_calls(d)
    assert calls and "No images in this run" in calls[0]["system"] and "images" not in calls[0]
    final = run(spec.model_copy(update={"max_evals": 4}), start, run_id="m", runs_root=tmp_path, which="mock")
    assert not any(r.critic_images for r in final["ledger"])  # the mock cannot see: nothing rendered


def test_image_text_switches_with_vision():
    assert "`cp`" in image_text(True) and "No images" in image_text(False)


def test_a_fatal_image_finding_vetoes_and_cannot_rescue(spec):
    good = CFDResult(cid=P.cid, fidelity="neuralfoil", status="converged", cl=-0.9, cd=0.012, confidence=0.95)
    rep = validate(good, P, spec, [])
    assert rep.ok
    fatal = Finding(
        observation="Cp area far smaller than the printed Cl implies",
        location="whole chord",
        source="cp",
        consistent_with_numeric=False,
        severity="fatal",
    )
    llm = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="NONE"), findings=[fatal], confidence=0.8)
    assert merge_verdict(rep, llm).status == "NON_PHYSICAL"  # vision can veto
    broken = CFDResult(cid=P.cid, fidelity="neuralfoil", status="converged", cl=0.9, cd=0.0001, confidence=0.95)
    bad = validate(broken, P, spec, [])
    assert not bad.ok
    ok_llm = Verdict(status="PASS", diagnosis=Diagnosis(symptom="NONE"), confidence=0.9)
    assert merge_verdict(bad, ok_llm).status == bad.failure_class  # vision cannot rescue


# ------------------------------------------------------------------ deterministic surface checks


def test_cp_integral_matches_the_reported_cl_and_flags_scaling(spec):
    from swarm.critic.surface import cl_from_cp, surface_data

    r = neuralfoil.evaluate(P, spec)
    s = surface_data(P, spec, r)
    assert abs(cl_from_cp(P, s) - r.cl) <= 0.05 + 0.12 * abs(r.cl)
    rep = validate(r, P, spec, [], surface=s)
    assert next(c for c in rep.checks if c.name == "cp_integral").ok and rep.ok
    scaled = r.model_copy(update={"cl": r.cl * 0.6, "cd": r.cd * 0.6})
    bad = validate(scaled, P, spec, [], surface=s)
    assert bad.failure_class == "NON_PHYSICAL" and not next(c for c in bad.checks if c.name == "cp_integral").ok


def test_cp_spike_flags_a_narrow_peak_only(spec):
    from swarm.critic.surface import cp_spike

    x = np.linspace(0, 1, 160)
    smooth = 1.0 - 2.5 * np.exp(-x / 0.3)  # a broad suction hump: no spike
    base = {"x": x, "cp": smooth}
    assert cp_spike({"suction": base}) == 0.0
    kinked = {"x": x, "cp": smooth - 0.5 * np.exp(-(((x - 0.3) / 0.008) ** 2))}
    assert cp_spike({"suction": kinked}) > 0.3
    r = CFDResult(cid=P.cid, fidelity="xfoil", status="converged", cl=-0.95, cd=0.012, solver_level=0)
    surf = surface_data(P, None, _xfoil_result())
    assert next(c for c in validate(r, P, spec, [], surface=surf).checks if c.name == "cp_smoothness").ok
    kink = {
        **surf,
        "suction": {**surf["suction"], "cp": surf["suction"]["cp"] - 0.6 * (abs(surf["suction"]["x"] - 0.3) < 0.012)},
    }
    bad = validate(r, P, spec, [], surface=kink)
    assert not next(c for c in bad.checks if c.name == "cp_smoothness").ok and bad.failure_class == "NON_PHYSICAL"


def test_without_surface_data_the_checks_are_absent(spec):
    r = neuralfoil.evaluate(P, spec)
    names = {c.name for c in validate(r, P, spec, []).checks}
    assert not names & {"cp_integral", "cp_smoothness"}
