"""Scoring of the CAD agent's sign predictions (milestone 2).

Each ParamChange states the expected sign of the change in race-car Cl (negative = downforce, so more
downforce is -1) and in Cd. A record's `predicted_signs` holds them per parameter; the measured change is
the record's result minus its parent's, at the same fidelity, both from the ledger.

- Joint prediction of a record: the common sign of its non-zero predictions (0 if all are 0). A record
  whose changes predict opposite signs makes no joint prediction ("mixed") and is not scored.
- A measured change within the deadband (CL_EPS, CD_EPS) counts as 0. A 0 prediction is right only
  then; a +/-1 prediction is right only if the measured change has that sign outside the deadband.
- Per parameter: single-change records (the change is attributable), and the implied sensitivity
  sign(prediction) * sign(parameter change), which shows whether the agent's physics for a parameter is
  consistent across proposals (e.g. "more alpha gives more downforce" is dCl/dalpha < 0 here).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from swarm.state import EvalRecord

CL_EPS = 0.002
CD_EPS = 0.0001


def _sign(x: float, eps: float) -> int:
    return 0 if abs(x) <= eps else (1 if x > 0 else -1)


def _usable(rec: EvalRecord) -> bool:
    r = rec.result
    return not rec.quarantined and r.cl is not None and r.cd is not None and math.isfinite(r.cl) and math.isfinite(r.cd)


def joint(signs: Iterable[int]) -> int | None:
    nz = {s for s in signs if s}
    if len(nz) > 1:
        return None
    return nz.pop() if nz else 0


def _tally() -> dict:
    return {"n": 0, "correct": 0}


def score(ledger: list[EvalRecord]) -> dict:
    out = {
        "records": 0,  # records with predictions and a comparable parent
        "no_parent": 0,  # predictions, but no usable parent result at the same fidelity
        "cl": _tally(),
        "cd": _tally(),
        "cl_mixed": 0,
        "cd_mixed": 0,
        "params": {},
    }
    seen: list[EvalRecord] = []
    for rec in ledger:
        if rec.predicted_signs and _usable(rec):
            parent = next(
                (
                    p
                    for p in reversed(seen)
                    if p.params.cid == rec.parent_cid and p.result.fidelity == rec.result.fidelity and _usable(p)
                ),
                None,
            )
            if parent is None:
                out["no_parent"] += 1
            else:
                _score_record(rec, parent, out)
        seen.append(rec)
    for t in (out["cl"], out["cd"]):
        t["accuracy"] = t["correct"] / t["n"] if t["n"] else None
    return out


def _score_record(rec: EvalRecord, parent: EvalRecord, out: dict) -> None:
    out["records"] += 1
    measured = {
        "cl": _sign(rec.result.cl - parent.result.cl, CL_EPS),
        "cd": _sign(rec.result.cd - parent.result.cd, CD_EPS),
    }
    preds = rec.predicted_signs
    for i, key in enumerate(("cl", "cd")):
        j = joint(s[i] for s in preds.values())
        if j is None:
            out[f"{key}_mixed"] += 1
            continue
        out[key]["n"] += 1
        out[key]["correct"] += j == measured[key]
    single = len(preds) == 1
    for name, (pcl, pcd) in preds.items():
        st = out["params"].setdefault(
            name,
            {
                "changes": 0,
                "single": 0,
                "single_cl_correct": 0,
                "single_cd_correct": 0,
                "implied_dcl": {-1: 0, 0: 0, 1: 0},
            },
        )
        st["changes"] += 1
        dv = _sign(getattr(rec.params, name) - getattr(parent.params, name), 0.0)
        if dv:
            st["implied_dcl"][pcl * dv] += 1
        if single:
            st["single"] += 1
            st["single_cl_correct"] += pcl == measured["cl"]
            st["single_cd_correct"] += pcd == measured["cd"]


def _acc(t: dict) -> str:
    return "n/a" if not t["n"] else f"{t['correct']}/{t['n']} ({100 * t['correct'] / t['n']:.0f}%)"


def report_section(ledger: list[EvalRecord]) -> list[str]:
    """Markdown lines for the run report; empty when no record could be scored."""
    s = score(ledger)
    if not s["records"]:
        return []
    out = [
        "## CAD sign predictions",
        "",
        f"{s['records']} proposals with a parent result at the same fidelity. Joint prediction (all changes "
        f"agree): Cl {_acc(s['cl'])}, Cd {_acc(s['cd'])}; not scored because the changes predicted opposite "
        f"signs: Cl {s['cl_mixed']}, Cd {s['cd_mixed']}.",
        "",
        "| parameter | changes | single-change proposals: Cl right | Cd right | implied dCl/dparam: − / 0 / + |",
        "|---|---|---|---|---|",
    ]
    for name, st in sorted(s["params"].items()):
        n = st["single"]
        cl = f"{st['single_cl_correct']}/{n}" if n else "—"
        cd = f"{st['single_cd_correct']}/{n}" if n else "—"
        imp = st["implied_dcl"]
        out.append(f"| {name} | {st['changes']} | {cl} | {cd} | {imp[-1]} / {imp[0]} / {imp[1]} |")
    out += [
        "",
        f"Signs are of the change in race-car Cl (negative = downforce) and in Cd, against the parent's result; "
        f"changes within ±{CL_EPS} (Cl) and ±{CD_EPS} (Cd) count as 0. Implied dCl/dparam = predicted sign × "
        "sign of the parameter change: a parameter split between − and + was argued both ways. From ledger.jsonl.",
        "",
    ]
    return out
