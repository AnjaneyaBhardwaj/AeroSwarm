"""Live server (swarm/live.py): a mock run streamed over SSE matches its own export; inputs are checked."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from swarm.live import create_app
from swarm.viz.export import export_run

START = {"main_camber": 0.06, "main_camber_pos": 0.4, "main_thickness": 0.13, "alpha_deg": 6.0}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv("AEROSWARM_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    viewer = tmp_path / "viewer"
    shutil.copytree("viewer", viewer, ignore=shutil.ignore_patterns("live"))
    app = create_app(viewer, tmp_path / "runs", tmp_path / "baselines", poll_s=0.05, baseline=False, with_cad=False)
    return TestClient(app), viewer, tmp_path / "runs"


def _sse(lines):
    event, out = None, []
    for line in lines:
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            out.append((event, json.loads(line[6:])))
    return out


def test_health_and_static(setup):
    client, _, _ = setup
    h = client.get("/api/health").json()
    assert h["ok"] and h["anthropic_key"] is False and h["busy"] is None and isinstance(h["xfoil"], bool)
    assert h["freecad"] is False  # with_cad=False
    assert h["defaults"]["model"] in h["models"] and h["caps"]["max_evals"] == 40
    assert set(h["bounds"]) == set(START)
    assert client.post("/api/check", json={"start": h["default_start"]}).json()["ok"] is True
    assert "Aeroptimize" in client.get("/").text
    assert 'id="live"' in client.get("/replay.html").text  # the replay, with the live-run panel
    assert client.get("/runs/index.json").json()["runs"][0]["name"] == "example_hard_llm"


def test_rejects_bad_requests(setup):
    client, _, _ = setup
    assert client.post("/api/check", json={"start": START}).json()["ok"] is True
    chk = client.post("/api/check", json={"start": {**START, "main_thickness": 0.10}}).json()
    assert chk["ok"] is False and "LE radius" in chk["violations"][0]
    assert client.post("/api/runs", json={"start": START}).status_code == 400  # no API key for anthropic
    bad = client.post("/api/runs", json={"start": {**START, "main_thickness": 0.10}, "llm": "mock"})
    assert bad.status_code == 400 and "geometry/rule" in bad.json()["detail"]
    assert client.post("/api/runs", json={"start": {**START, "alpha_deg": 30}, "llm": "mock"}).status_code == 400
    assert client.post("/api/runs", json={"start": START, "llm": "mock", "max_evals": 41}).status_code == 422
    assert client.post("/api/runs", json={"start": {"flap": 1}, "llm": "mock"}).status_code == 400
    assert client.get("/api/runs/nope/stream").status_code == 404


def test_mock_run_streams_the_export(setup):
    client, viewer, runs = setup
    r = client.post("/api/runs", json={"start": START, "llm": "mock", "max_evals": 4, "inner_optimizer": False})
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    with client.stream("GET", f"/api/runs/{rid}/stream") as s:
        events = _sse(s.iter_lines())
    kinds = [k for k, _ in events]
    assert kinds[0] == "run" and kinds[-1] == "done" and "progress" in kinds
    head = events[0][1]
    assert head["start"] == START and head["is_mock"] and head["start_cid"] in head["outlines"]
    gens = [d["generation"] for k, d in events if k == "generation"]
    final = events[-1][1]
    assert [g["gen"] for g in gens] == [g["gen"] for g in final["generations"] if g["head"] >= 0]
    assert gens == [g for g in final["generations"] if g["head"] >= 0]  # streamed records == the saved export
    assert final == export_run(runs / rid, name=f"live_{rid}")
    saved = Path(viewer / "runs" / "live" / f"live_{rid}.json")
    assert json.loads(saved.read_text())["name"] == f"live_{rid}"
    idx = client.get("/runs/index.json").json()["runs"]
    assert any(e["file"] == f"live/live_{rid}.json" for e in idx)
    assert client.get(f"/runs/live/live_{rid}.json").status_code == 200


def test_stop_ends_the_run_with_its_own_label(setup):
    client, _, _ = setup
    r = client.post("/api/runs", json={"start": START, "llm": "mock", "max_evals": 40, "inner_optimizer": False})
    rid = r.json()["run_id"]
    assert client.post(f"/api/runs/{rid}/stop", json={"token": "wrong"}).status_code == 403
    assert client.post(f"/api/runs/{rid}/stop", json={"token": r.json()["control_token"]}).json()["run_id"] == rid
    with client.stream("GET", f"/api/runs/{rid}/stream") as s:
        events = _sse(s.iter_lines())
    final = events[-1]
    assert final[0] == "done", final
    assert final[1]["termination"] == "stopped" and final[1]["evals"] < 40
    phases = [d for k, d in events if k == "progress"]
    assert all("phase" in p for p in phases)
    assert client.post("/api/runs/nope/stop", json={"token": ""}).status_code == 404


def _public_app(tmp_path, monkeypatch, **kw):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")  # requests below are refused before any LLM call
    viewer = tmp_path / "viewer"
    shutil.copytree("viewer", viewer, ignore=shutil.ignore_patterns("live"))
    return TestClient(
        create_app(viewer, tmp_path / "runs", tmp_path / "baselines", poll_s=0.05, baseline=False, with_cad=False, **kw)
    )


def test_access_code_and_daily_cap(tmp_path, monkeypatch):
    client = _public_app(tmp_path, monkeypatch, access_code="s3cret", daily_usd=1.0)
    h = client.get("/api/health").json()
    assert h["access_code_required"] is True and h["daily"] == {"cap_usd": 1.0, "spent_usd": 0.0}
    body = {"start": START, "llm": "anthropic", "budget_usd": 0.5}
    assert client.post("/api/runs", json=body).status_code == 403
    assert client.post("/api/runs", json={**body, "access_code": "nope"}).status_code == 403
    # over today's cap: refused before a run (or an LLM call) starts
    over = client.post("/api/runs", json={**body, "access_code": "s3cret", "budget_usd": 2.0})
    assert over.status_code == 429 and "budget" in over.json()["detail"]
    # the mock stays open without the code
    ok = client.post("/api/runs", json={"start": START, "llm": "mock", "max_evals": 2, "inner_optimizer": False})
    assert ok.status_code == 200


def test_daily_spend_reserve_and_settle(tmp_path):
    from swarm.live import DailySpend

    d = DailySpend(tmp_path / "spend.json", cap_usd=2.0)
    assert d.reserve(1.5) and not d.reserve(1.0)
    d.settle(1.5, 0.4)  # the run spent less than its cap: the rest is freed
    assert abs(d.spent() - 0.4) < 1e-9 and d.reserve(1.5)
    assert abs(DailySpend(tmp_path / "spend.json", 2.0).spent() - 1.9) < 1e-9  # survives a restart


def test_cors_only_for_listed_origins(tmp_path, monkeypatch):
    client = _public_app(tmp_path, monkeypatch, cors_origins=["https://example.org"])
    ok = client.get("/api/health", headers={"Origin": "https://example.org"})
    assert ok.headers.get("access-control-allow-origin") == "https://example.org"
    other = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_refuses_public_bind_without_access_code(monkeypatch):
    from swarm import live

    monkeypatch.delenv("AEROSWARM_LIVE_ACCESS_CODE", raising=False)
    with pytest.raises(SystemExit, match="refusing to listen"):
        live.main(["--host", "0.0.0.0"])
