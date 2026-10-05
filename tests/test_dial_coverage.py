"""Dial-coverage summary in the Chief brief: range explored, moves, last move per free parameter."""

from __future__ import annotations

from test_loop_fixes import rec, wp

from swarm.briefs import chief_brief
from swarm.ledger import dial_coverage
from swarm.state import free_params


def _ledger():
    a = rec(wp(4.0), -1.2, gen=0)
    b = rec(wp(5.0), -1.3, gen=1).model_copy(update={"parent_cid": a.params.cid})
    c = rec(wp(5.0, camber=0.06), -1.4, gen=2, fid="neuralfoil").model_copy(update={"parent_cid": b.params.cid})
    c_x = rec(wp(5.0, camber=0.06), -1.38, gen=3).model_copy(update={"parent_cid": c.params.cid})  # promotion
    d = rec(wp(4.5), -1.25, gen=4).model_copy(update={"parent_cid": b.params.cid})
    return [a, b, c, c_x, d]


def test_dial_coverage_counts_moves_against_the_parent(spec):
    cov = {c["param"]: c for c in dial_coverage(_ledger(), list(free_params(spec)))}
    al = cov["alpha_deg"]
    assert al["explored"] == [4.0, 5.0] and al["moves"] == 2 and (al["up"], al["down"]) == (1, 1)
    assert al["last_move"] == {"gen": 4, "from": 5.0, "to": 4.5}
    assert al["share_of_range"] == round(1.0 / 16.0, 3)
    cam = cov["main_camber"]
    assert cam["explored"] == [0.05, 0.06] and cam["moves"] == 1 and cam["last_move"]["gen"] == 2  # promotion: no move
    th = cov["main_thickness"]
    assert th["moves"] == 0 and th["last_move"] is None and th["share_of_range"] == 0.0


def test_chief_brief_shows_dial_coverage(spec):
    ledger = _ledger()
    state = {"spec": spec, "ledger": ledger, "generation": 5, "events": [], "history": [], "strategy": None}
    b = chief_brief(state, {})
    assert [c["param"] for c in b.facts["dial_coverage"]] == list(free_params(spec))
    assert "## Dial coverage (all evaluated designs; a move = a design whose value differs from its parent's)" in b.user
    assert "| alpha_deg | -2–14 | 4–5 | 6% | 2 (1/1) | gen 4: 5 → 4.5 |" in b.user
    assert "| main_thickness | 0.08–0.18 | 0.12–0.12 | 0% | 0 (0/0) | never moved |" in b.user
