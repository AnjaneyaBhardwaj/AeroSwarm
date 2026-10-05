"""Plateau policy: no plateau termination before 80% of the eval budget; exploration instead."""

from __future__ import annotations

import json

from test_loop_fixes import delta, memo, rec, wp

from swarm.briefs import chief_brief
from swarm.explore import (
    RESTART_DISTANCE,
    WIDEN_RADIUS,
    current_parent,
    distance,
    handle_plateau,
    plateau_allowed_after,
    restart_anchor,
)
from swarm.llm.client import ScriptedClient
from swarm.run import run
from swarm.state import Diagnosis, Verdict, free_params


def _state(spec, ledger, gen=3, events=(), **kw):
    return {"spec": spec, "ledger": ledger, "generation": gen, "events": list(events), "history": []} | kw


def plateau(**kw):
    return memo([{"name": "alpha_deg", "direction": "-"}], radius=0.05, declare_plateau=True, **kw)


def test_plateau_is_allowed_only_after_80_percent_of_the_budget(spec):
    assert plateau_allowed_after(spec.model_copy(update={"max_evals": 40})) == 32
    assert plateau_allowed_after(spec.model_copy(update={"max_evals": 5})) == 4
    ledger = [rec(wp(4.0 + 0.25 * i), -1.2, gen=i) for i in range(32)]
    s40 = spec.model_copy(update={"max_evals": 40})
    m, ev, br = handle_plateau(plateau(), _state(s40, ledger), ledger[-1].params)
    assert m.declare_plateau and ev == [] and br is None  # 32 of 40: the plateau stands
    m, ev, br = handle_plateau(plateau(), _state(s40, ledger[:31]), ledger[30].params)
    assert not m.declare_plateau and ev[0]["event"] == "plateau_deferred" and ev[0]["allowed_after"] == 32


def test_first_deferral_widens_the_trust_region_and_pads_the_focus(spec):
    ledger = [rec(wp(4.0), -1.2), rec(wp(4.5), -1.25, gen=2)]
    m, ev, br = handle_plateau(plateau(), _state(spec, ledger), ledger[1].params)
    assert br is None and ev[0]["action"] == "widen" and ev[0]["trust_radius"] == [0.05, WIDEN_RADIUS]
    assert m.trust_radius == WIDEN_RADIUS and not m.declare_plateau
    assert m.focus_names[0] == "alpha_deg" and len(m.focus_names) == 3
    assert m.direction("alpha_deg") == "-"  # widen keeps the Chief's directions


def test_second_deferral_restarts_from_a_different_region(spec):
    near = rec(wp(4.2), -1.30, gen=1)  # closest to the target, but next to the current base
    base = rec(wp(4.0), -1.25, gen=2)
    far_bad = rec(wp(12.0, camber=0.02), -0.8, gen=3)
    far_good = rec(wp(10.0, camber=0.08), -1.35, gen=4)
    ledger = [near, base, far_bad, far_good]
    prev = [{"event": "plateau_deferred", "action": "widen", "gen": 2}]
    m, ev, br = handle_plateau(plateau(), _state(spec, ledger, gen=5, events=prev), base.params)
    assert ev[0]["action"] == "restart" and ev[0]["anchor_cid"] == far_good.params.cid
    assert br == {"anchor_cid": far_good.params.cid, "from_gen": 5, "until_gen": 7}
    assert all(f.direction == "free" for f in m.focus_params) and m.trust_radius >= 0.15
    names = list(free_params(spec))
    assert distance(far_good.params, base.params, names) >= RESTART_DISTANCE > distance(near.params, base.params, names)
    # a later restart avoids the earlier anchor as well
    prev2 = prev + [{"event": "plateau_deferred", "action": "restart", "anchor_cid": far_good.params.cid, "gen": 5}]
    prev2 += [{"event": "plateau_deferred", "action": "widen", "gen": 6}]
    _, ev2, _ = handle_plateau(plateau(), _state(spec, ledger, gen=8, events=prev2), base.params)
    assert ev2[0]["anchor_cid"] == far_bad.params.cid


def test_restart_falls_back_to_the_farthest_design_or_widen(spec):
    a, b = rec(wp(4.0), -1.2), rec(wp(4.3), -1.25)
    anchor, why = restart_anchor([a, b], spec, [b.params])
    assert anchor.params.cid == a.params.cid and why.startswith("farthest")
    prev = [{"event": "plateau_deferred", "action": "widen", "gen": 1}]
    m, ev, br = handle_plateau(plateau(), _state(spec, [a], events=prev), a.params)
    assert br is None and ev[0]["action"] == "widen" and "restart_skipped" in ev[0]


def test_a_promotion_with_a_plateau_flag_promotes(spec):
    ledger = [rec(wp(4.0), -1.5, fid="neuralfoil")]
    m, ev, br = handle_plateau(plateau(promote_cid=ledger[0].params.cid), _state(spec, ledger), ledger[0].params)
    assert ev[0]["action"] == "promotion" and m.promote_cid == ledger[0].params.cid and not m.declare_plateau


def test_parent_stays_on_the_restart_branch_while_it_is_active(spec):
    best = rec(wp(4.0), -1.49, gen=1)  # the global best
    anchor = rec(wp(10.0, camber=0.08), -1.30, gen=2)
    child = rec(wp(9.5, camber=0.08), -1.38, gen=5)  # first evaluated on the branch
    ledger = [best, anchor, child]
    branch = {"anchor_cid": anchor.params.cid, "from_gen": 5, "until_gen": 7}
    p, why = current_parent(_state(spec, ledger, gen=6, exploration=branch))
    assert p.params.cid == child.params.cid and why.startswith(f"restart branch from {anchor.params.cid}")
    p, _ = current_parent(_state(spec, ledger, gen=8, exploration=branch))  # window over
    assert p.params.cid == best.params.cid
    b = chief_brief(_state(spec, ledger, gen=6, exploration=branch, strategy=None), {})
    assert b.facts["parent"]["cid"] == child.params.cid and b.facts["restart_branch"] == branch
    assert "declare_plateau ends the run only after 24 of 30 evaluations" in b.user


def test_graph_explores_instead_of_ending_on_an_early_plateau(spec, start, tmp_path):
    """max_evals 5: plateaus at gens 1-3 explore (widen, restart, widen); at gen 4 (4 evals) the
    plateau ends the run."""
    v = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="INSUFFICIENT_LOADING"), confidence=0.6)
    m0 = memo(["alpha_deg"], radius=0.3)
    script = [m0, v]  # gen 0: baseline
    script += [plateau(), delta("alpha_deg", 1.5), v]  # gen 1: widen (r 0.05 would stop alpha at 3.2)
    script += [plateau(), delta("main_camber", 0.05), v]  # gen 2: restart
    script += [plateau(), delta("main_camber_pos", 0.45), v]  # gen 3: widen
    script += [plateau()]  # gen 4: 4 of 5 evals used, the plateau stands
    llm = ScriptedClient(script)
    final = run(spec.model_copy(update={"max_evals": 5}), start, run_id="pl", runs_root=tmp_path, llm=llm)
    assert not llm.responses and final["termination"] == "plateau" and len(final["ledger"]) == 4
    events = [json.loads(x) for x in (tmp_path / "pl" / "events.jsonl").read_text().splitlines()]
    dfr = [e for e in events if e.get("event") == "plateau_deferred"]
    assert [(e["gen"], e["action"]) for e in dfr] == [(1, "widen"), (2, "restart"), (3, "widen")]
    rs = dfr[1]
    assert rs["anchor_cid"] != rs["from_cid"]
    gen2 = next(r for r in final["ledger"] if r.generation == 2)
    assert gen2.parent_cid == rs["anchor_cid"]  # the CAD step started from the restart anchor
    gen3 = next(r for r in final["ledger"] if r.generation == 3)
    assert gen3.parent_cid in (rs["anchor_cid"], gen2.params.cid)  # still on the branch
    last_chief = [c for c in llm.calls if c["role"] == "chief"][-1]["user"]
    assert "(plateau deferred: restart from " in last_chief and "(plateau deferred: widen)" in last_chief
    report = (tmp_path / "pl" / "report.md").read_text()
    assert "- Plateau declarations deferred (allowed after 4 evals): gen 1 widen" in report
