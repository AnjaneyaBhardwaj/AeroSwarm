"""Critic failure zoo (milestone 3, BLUEPRINT §3 "Evaluate the Critic itself"): labelled evaluations whose
numbers can or cannot be trusted, and the Critic's precision / recall with and without images.

A case is what the Critic receives for one evaluation: the design, the solver result, the surface data its
images are drawn from, the parent design, and (for an XFoil result) the NeuralFoil record of the same design,
as a run's ledger would hold. Labels:
- "trust": the numbers are a correct solution of the stated geometry (a separated design is trustworthy:
  it is a bad design, not a bad result);
- "flag": the numbers should not be accepted (under-resolved solve, a wrong solution branch, coefficients
  inconsistent with the surface data, stale images, a geometry defect, a sign or reference error).

Flagged = the merged verdict is NON_PHYSICAL or NUMERICAL_FAILURE, or a finding is "fatal" (hard flag).
"Soft" also counts a doubt about the numbers short of that: a failed fidelity-gap or surrogate-confidence
check, or a "suspect" finding the Critic marks inconsistent with the numeric data. Checks about the design
(TE separation, stall margin, the NeuralFoil screen) are not doubts about the numbers and do not count.

Arms: numeric (the deterministic validators alone, no LLM), llm_text (the Critic without images),
llm_vision (the Critic with the rendered images). Cases are cached in evals/critic_zoo.json (surface data,
not PNGs; images are re-rendered from it).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from swarm.agents.critic import merge_verdict, review
from swarm.critic.numeric import suggest_diagnosis, validate
from swarm.critic.render import render
from swarm.state import CFDResult, DesignSpec, Diagnosis, EvalRecord, Verdict, WingParams

ARMS = ("numeric", "llm_text", "llm_vision")
HARD = ("NON_PHYSICAL", "NUMERICAL_FAILURE")
TRUST_CHECKS = ("fidelity_gap", "surrogate_confidence")  # suspect checks that doubt the numbers, not the design

KINDS: dict[str, tuple[str, str]] = {
    # kind: (label, what it is)
    "clean_xfoil": ("trust", "XFoil result near the target, attached flow"),
    "clean_neuralfoil": ("trust", "NeuralFoil result near the target"),
    "separated": (
        "trust",
        "converged XFoil result with real trailing-edge separation (a bad design, not a bad result)",
    ),
    "coarse_panels": ("flag", "XFoil solved with 40 panels: converged, plausible, under-resolved"),
    "wrong_branch": ("flag", "XFoil direct solve on a low-lift branch; alpha continuation gives a different answer"),
    "reference_scaled": ("flag", "Cl and Cd scaled by 0.6 (wrong reference length); surface data unchanged"),
    "stale_images": ("flag", "numbers of this design, surface data of another design"),
    "surface_kink": ("flag", "a 0.4% c bump on the suction side at x/c 0.3 (geometry defect), solved by XFoil"),
    "sign_flip": ("flag", "upright-frame Cl reported (sign not negated)"),
    "drag_reference": ("flag", "Cd divided by 5 (wrong reference)"),
}


def _record(params: WingParams, result: CFDResult) -> EvalRecord:
    v = Verdict(status="TARGET_MISS", diagnosis=Diagnosis(symptom="NONE"), confidence=0.5)
    return EvalRecord(generation=0, params=params, result=result, verdict=v, rationale="")


def load_case(c: dict) -> dict:
    """JSON case -> objects (params, results, surfaces as numpy arrays)."""

    def surf(s: dict | None) -> dict | None:
        if s is None:
            return None
        return {
            "source": s["source"],
            **{side: {k: np.asarray(v) for k, v in s[side].items()} for side in ("suction", "pressure")},
        }

    par = c.get("parent")
    return {
        **c,
        "params": WingParams(**c["params"]),
        "result": CFDResult(**c["result"]),
        "surface": surf(c["surface"]),
        "other_tier": CFDResult(**c["other_tier"]) if c.get("other_tier") else None,
        "parent": None
        if par is None
        else {
            "params": WingParams(**par["params"]),
            "result": CFDResult(**par["result"]),
            "surface": surf(par["surface"]),
        },
    }


def dump_surface(s: dict | None) -> dict | None:
    if s is None:
        return None
    return {
        "source": s["source"],
        **{side: {k: [round(float(x), 6) for x in v] for k, v in s[side].items()} for side in ("suction", "pressure")},
    }


def state_for(case: dict, spec: DesignSpec) -> tuple[dict, EvalRecord | None]:
    """The Critic's inputs as the graph would build them."""
    ledger = [_record(case["params"], case["other_tier"])] if case["other_tier"] is not None else []
    rep = validate(case["result"], case["params"], spec, ledger)
    par = case["parent"]
    parent_rec = _record(par["params"], par["result"]) if par else None
    state = {"spec": spec, "params": case["params"], "result": case["result"], "numeric": rep}
    return state, parent_rec


def images_for(case: dict, spec: DesignSpec, out_dir: str | Path) -> dict[str, str]:
    par = case["parent"]
    return render(
        case["params"],
        case["result"],
        spec,
        out_dir,
        parent=(par["params"], par["result"]) if par else None,
        surface=case["surface"],
        parent_surface=par["surface"] if par else None,
    )


def flags(v: Verdict, numeric_doubt: bool) -> dict[str, bool]:
    hard = v.status in HARD or any(f.severity == "fatal" for f in v.findings)
    doubt = any(f.severity == "suspect" and not f.consistent_with_numeric for f in v.findings)
    soft = hard or numeric_doubt or doubt
    return {"hard": hard, "soft": soft}


def judge(case: dict, spec: DesignSpec, arm: str, llm=None, image_dir: str | Path | None = None) -> dict:
    """One case through one arm: the verdict and whether it flags the result."""
    state, parent_rec = state_for(case, spec)
    rep = state["numeric"]
    numeric_doubt = any(not c.ok and c.name in TRUST_CHECKS for c in rep.checks)
    if arm == "numeric":
        diag = suggest_diagnosis(case["result"], spec, parent_rec.result if parent_rec else None)
        v = Verdict(status=rep.status, diagnosis=diag, confidence=1.0)
    else:
        images = images_for(case, spec, Path(image_dir) / case["name"]) if arm == "llm_vision" else None
        v = review(llm, state, parent_rec, images=images)
        v = merge_verdict(rep, v)
    return {
        "name": case["name"],
        "kind": case["kind"],
        "label": case["label"],
        "arm": arm,
        "numeric_status": rep.status,
        "status": v.status,
        "symptom": v.diagnosis.symptom,
        "findings": [f.model_dump() for f in v.findings],
        **flags(v, numeric_doubt),
    }


def score(rows: list[dict], key: str = "hard") -> dict:
    """Precision / recall of flagging the "flag" cases."""
    tp = sum(r[key] and r["label"] == "flag" for r in rows)
    fp = sum(r[key] and r["label"] == "trust" for r in rows)
    fn = sum(not r[key] and r["label"] == "flag" for r in rows)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def run_arm(
    cases: list[dict], spec: DesignSpec, arm: str, llm=None, image_dir: str | Path | None = None, log=print
) -> list[dict]:
    rows = []
    for c in cases:
        try:
            rows.append(judge(c, spec, arm, llm, image_dir))
        except Exception as e:  # an LLM failure is recorded, not scored as a verdict
            rows.append({"name": c["name"], "kind": c["kind"], "label": c["label"], "arm": arm, "error": repr(e)[:300]})
        log(f"{arm} {c['name']}: {rows[-1].get('status', rows[-1].get('error'))}")
    return rows


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.0f}%"


def markdown(cases: list[dict], results: dict[str, list[dict]], meta: dict) -> str:
    out = [
        "# Critic evaluation (failure zoo)",
        "",
        "Generated by `scripts/critic_eval.py report` from `evals/critic_zoo.json` (cases, built "
        f"{meta.get('built', '?')}) and `evals/critic_results_<arm>.json`. A case is what the Critic receives for "
        "one evaluation; label `flag` = the numbers should not be accepted, `trust` = they are a correct solution "
        "(a separated design is `trust`). Hard flag = verdict NON_PHYSICAL / NUMERICAL_FAILURE or a fatal finding; "
        "soft flag also counts a failed fidelity-gap / surrogate-confidence check or a suspect finding marked "
        "inconsistent with the numbers (design checks such as TE separation do not count).",
        "",
        "## Cases",
        "",
        "| kind | label | cases | what it is |",
        "|---|---|---|---|",
    ]
    for kind, (label, text) in KINDS.items():
        n = sum(c["kind"] == kind for c in cases)
        if n:
            out.append(f"| {kind} | {label} | {n} | {text} |")
    out += [
        "",
        "## Precision and recall",
        "",
        "| arm | cases judged | errors | hard: precision | hard: recall | soft: precision | soft: recall |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        rows = results.get(arm)
        if not rows:
            out.append(f"| {arm} | not run | | | | | |")
            continue
        ok = [r for r in rows if "error" not in r]
        h, s = score(ok, "hard"), score(ok, "soft")
        out.append(
            f"| {arm} | {len(ok)} | {len(rows) - len(ok)} | {_pct(h['precision'])} ({h['tp']}/{h['tp'] + h['fp']}) "
            f"| {_pct(h['recall'])} ({h['tp']}/{h['tp'] + h['fn']}) | {_pct(s['precision'])} | {_pct(s['recall'])} |"
        )
    run_arms = [a for a in ARMS if results.get(a)]
    out += ["", "## By kind (hard flags / cases)", "", "| kind | label | " + " | ".join(run_arms) + " |"]
    out.append("|---|---|" + "---|" * len(run_arms))
    for kind, (label, _) in KINDS.items():
        cells = []
        for arm in run_arms:
            rows = [r for r in results[arm] if r["kind"] == kind and "error" not in r]
            cells.append(f"{sum(r['hard'] for r in rows)}/{len(rows)}" if rows else "—")
        if any(c != "—" for c in cells):
            out.append(f"| {kind} | {label} | " + " | ".join(cells) + " |")
    out += ["", "## Per case", "", "| case | label | " + " | ".join(f"{a} status (flag)" for a in run_arms) + " |"]
    out.append("|---|---|" + "---|" * len(run_arms))
    by = {a: {r["name"]: r for r in results[a]} for a in run_arms}
    for c in cases:
        cells = []
        for a in run_arms:
            r = by[a].get(c["name"])
            if r is None:
                cells.append("—")
            elif "error" in r:
                cells.append("error")
            else:
                cells.append(f"{r['status']} ({'hard' if r['hard'] else 'soft' if r['soft'] else '-'})")
        out.append(f"| {c['name']} | {c['label']} | " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


def build_cases(
    spec: DesignSpec,
    solve: Callable[..., CFDResult],
    surface: Callable[[WingParams, CFDResult], dict | None],
    nf: Callable[[WingParams], CFDResult],
) -> list[dict]:
    """Deterministic case list. `solve(params, level=0, npanel=None, coords=None)` -> XFoil result whose
    surface `surface(params, result)` can read; `nf(params)` -> NeuralFoil result."""
    W = WingParams

    def xf_case(name, kind, p, parent, r=None, surf=None, result_update=None, parent_surf=None):
        r = r or solve(p)
        s = surf if surf is not None else surface(p, r)
        res = r.model_copy(update=result_update or {})
        pr = solve(parent)
        return {
            "name": name,
            "kind": kind,
            "label": KINDS[kind][0],
            "params": p.model_dump(),
            "result": res.model_dump(exclude={"artifacts", "log_path"}),
            "surface": dump_surface(s),
            "other_tier": nf(p).model_dump(),
            "parent": {
                "params": parent.model_dump(),
                "result": pr.model_dump(exclude={"artifacts", "log_path"}),
                "surface": dump_surface(parent_surf if parent_surf is not None else surface(parent, pr)),
            },
        }

    ref = W(main_camber=0.08, main_camber_pos=0.35, main_thickness=0.135, alpha_deg=8.75)
    near = [
        W(main_camber=0.085, main_camber_pos=0.35, main_thickness=0.135, alpha_deg=8.75),
        W(main_camber=0.08, main_camber_pos=0.4, main_thickness=0.135, alpha_deg=9.5),
        W(main_camber=0.09, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=7.5),
        W(main_camber=0.07, main_camber_pos=0.35, main_thickness=0.14, alpha_deg=10.0),
    ]
    cases = []
    for i, p in enumerate(near):
        cases.append(xf_case(f"clean_xfoil_{i}", "clean_xfoil", p, ref))
    for i, p in enumerate(near):
        r, pr = nf(p), nf(ref)
        cases.append(
            {
                "name": f"clean_neuralfoil_{i}",
                "kind": "clean_neuralfoil",
                "label": "trust",
                "params": p.model_dump(),
                "result": r.model_dump(),
                "surface": dump_surface(surface(p, r)),
                "other_tier": None,
                "parent": {
                    "params": ref.model_dump(),
                    "result": pr.model_dump(),
                    "surface": dump_surface(surface(ref, pr)),
                },
            }
        )
    for i, p in enumerate(
        [
            W(main_camber=0.09, main_camber_pos=0.6, main_thickness=0.13, alpha_deg=14.0),
            W(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.18, alpha_deg=13.0),
            W(main_camber=0.09, main_camber_pos=0.55, main_thickness=0.13, alpha_deg=12.5),
        ]
    ):
        cases.append(xf_case(f"separated_{i}", "separated", p, ref))
    for i, p in enumerate(near[:3]):
        cases.append(xf_case(f"coarse_panels_{i}", "coarse_panels", p, ref, r=solve(p, npanel=40)))
    for i, (p, lvl) in enumerate(
        [
            (W(main_camber=0.06, main_camber_pos=0.4, main_thickness=0.08, alpha_deg=14.0), 0),
            (W(main_camber=0.02, main_camber_pos=0.4, main_thickness=0.1, alpha_deg=14.0), 1),
        ]
    ):
        cases.append(xf_case(f"wrong_branch_{i}", "wrong_branch", p, ref, r=solve(p, level=lvl)))
    for i, p in enumerate(near[:3]):
        r = solve(p)
        cases.append(
            xf_case(
                f"reference_scaled_{i}",
                "reference_scaled",
                p,
                ref,
                r=r,
                result_update={"cl": r.cl * 0.6, "cd": r.cd * 0.6},
            )
        )
    for i, (p, other) in enumerate(
        [(near[0], W(main_camber=0.04, main_camber_pos=0.4, main_thickness=0.13, alpha_deg=4.0)), (near[1], near[3])]
    ):
        cases.append(xf_case(f"stale_images_{i}", "stale_images", p, ref, surf=surface(other, solve(other))))
    for i, p in enumerate(near[:2]):
        cases.append(xf_case(f"surface_kink_{i}", "surface_kink", p, ref, r=solve(p, kink=True)))
    for i, p in enumerate(near[:2]):
        r = solve(p)
        cases.append(xf_case(f"sign_flip_{i}", "sign_flip", p, ref, r=r, result_update={"cl": -r.cl}))
    r = solve(near[2])
    cases.append(xf_case("drag_reference_0", "drag_reference", near[2], ref, r=r, result_update={"cd": r.cd / 5}))
    return cases
