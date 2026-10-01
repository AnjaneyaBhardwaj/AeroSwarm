"""Deterministic numeric validators (BLUEPRINT §3). Authoritative over any LLM.

Every threshold lives in `ValidatorConfig`; see that class for provenance.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel

from swarm.state import (
    TERMINAL_FIDELITIES,
    CFDResult,
    DesignSpec,
    Diagnosis,
    EvalRecord,
    VerdictStatus,
    WingParams,
)


class ValidatorConfig(BaseModel, frozen=True):
    """All validator thresholds in one place.

    These are PROJECT CONVENTIONS to calibrate against validation cases, NOT
    published limits. They are loose margins around sourced values
    (BLUEPRINT appendix "Where every number comes from"): NACA 4412 at
    Re 1e6 has Cl,max ≈ 1.67, min Cd ≈ 0.0060, max L/D ≈ 130 [S1]; NASA
    two-element Cl,max 2.82-3.32 [S6]; flat-plate friction (two sides)
    0.0029 laminar / 0.0097 turbulent.
    """

    cd_floor: float = 0.005  # below this: mesh leak / wrong reference values
    cl_ceiling_1el: float = 2.2  # |Cl| above this on one element is non-physical
    cl_ceiling_2el: float = 4.0
    ld_max: float = 200.0  # L/D above this suggests an integration error
    fidelity_gap_max: float = 0.1  # |ΔCl| between tiers on the same candidate
    surrogate_confidence_min: float = 0.7  # NeuralFoil analysis_confidence; below → escalate to XFoil
    sign_ambiguous_deg: float = 1.0  # skip the lift-sign check this close to zero lift
    # Convergence criteria for iterative solvers (OpenFOAM tiers; unused at T0/T1).
    residual_drop_orders_p: float = 4.0
    residual_drop_orders_U: float = 5.0
    coeff_rel_std_max: float = 0.005  # Cl, Cd relative std over the window
    coeff_window_iters: int = 300


VALIDATION = ValidatorConfig()

FailureClass = Literal["NON_PHYSICAL", "NUMERICAL_FAILURE", "UNSTEADY"]


class Check(BaseModel):
    name: str
    ok: bool
    value: float | str | None = None
    threshold: str = ""
    message: str = ""
    severity: Literal["fatal", "suspect", "skipped"] = "fatal"
    failure_class: FailureClass | None = None


class NumericReport(BaseModel):
    checks: list[Check]
    failure_class: FailureClass | None = None
    target_met: bool = False  # coefficients inside the target box (any fidelity)
    terminal: bool = False  # target met at a fidelity allowed to end the run
    suspect: bool = False  # a non-fatal check failed; blocks PASS

    @property
    def ok(self) -> bool:
        return self.failure_class is None

    @property
    def status(self) -> VerdictStatus:
        if self.failure_class:
            return self.failure_class
        return "PASS" if self.target_met and not self.suspect else "TARGET_MISS"


def in_target(result: CFDResult, spec: DesignSpec) -> bool:
    return (
        result.cl is not None
        and result.cd is not None
        and abs(result.cl - spec.target_cl) <= spec.cl_tol
        and result.cd <= spec.cd_max
    )


def nonfinite_fields(result: CFDResult) -> list[str]:
    """Names of solver outputs that are NaN/inf.

    Covers Cl, Cd, Cm and the Cf-derived boundary-layer facts (TE Cf,
    separation/transition x/c, bubble extents). XFoil runs with FP traps off,
    so a blown-up solve can print NaN instead of aborting; the parser drops
    those rows, and this check is the second line of defence for every tier.
    """
    vals: list[tuple[str, float | None]] = [("cl", result.cl), ("cd", result.cd), ("cm", result.cm)]
    bl = result.bl
    if bl is not None:
        vals += [("cf_te", bl.cf_te), ("te_separation_xc", bl.te_separation_xc), ("transition_xc", bl.transition_xc)]
        vals += [(f"bubble[{i}]", v) for i, b in enumerate(bl.bubbles) for v in b]
    return [n for n, v in vals if v is not None and not math.isfinite(v)]


def expected_lift_sign(params: WingParams, cfg: ValidatorConfig = VALIDATION) -> int:
    """Thin-airfoil estimate of the upright lift sign (α_L0 ≈ -100·m degrees)."""
    eff = params.alpha_deg + 100.0 * params.main_camber
    if abs(eff) < cfg.sign_ambiguous_deg:
        return 0
    return 1 if eff > 0 else -1


def validate(
    result: CFDResult | None,
    params: WingParams,
    spec: DesignSpec,
    ledger: list[EvalRecord],
    cfg: ValidatorConfig = VALIDATION,
) -> NumericReport:
    if result is None:
        c = Check(name="result_present", ok=False, message="no solver result", failure_class="NUMERICAL_FAILURE")
        return NumericReport(checks=[c], failure_class="NUMERICAL_FAILURE")

    checks: list[Check] = []
    conv = result.status == "converged" and result.cl is not None and result.cd is not None
    checks.append(
        Check(
            name="convergence",
            ok=conv,
            value=result.status,
            threshold="converged",
            message=result.failure_signature or "",
            failure_class=None if conv else ("UNSTEADY" if result.status == "unsteady" else "NUMERICAL_FAILURE"),
        )
    )
    if not conv:
        return NumericReport(checks=checks, failure_class=checks[0].failure_class)

    bad = nonfinite_fields(result)
    checks.append(
        Check(
            name="finite",
            ok=not bad,
            value=", ".join(bad) or None,
            threshold="Cl, Cd, Cm, Cf finite",
            message="solver produced NaN/inf (FP traps are off in our XFoil build)",
            failure_class="NUMERICAL_FAILURE",
        )
    )
    if bad:
        return NumericReport(checks=checks, failure_class="NUMERICAL_FAILURE")

    cl, cd = result.cl, result.cd
    two_el = params.flap_chord_ratio > 0
    ceiling = cfg.cl_ceiling_2el if two_el else cfg.cl_ceiling_1el
    checks.append(
        Check(
            name="drag_floor",
            ok=cd >= cfg.cd_floor,
            value=cd,
            threshold=f">= {cfg.cd_floor}",
            message="Cd below skin-friction floor",
            failure_class="NON_PHYSICAL",
        )
    )
    checks.append(
        Check(
            name="lift_ceiling",
            ok=abs(cl) <= ceiling,
            value=cl,
            threshold=f"|Cl| <= {ceiling}",
            message="non-physical lift",
            failure_class="NON_PHYSICAL",
        )
    )
    ld = abs(cl) / cd if cd > 0 else float("inf")
    checks.append(
        Check(
            name="l_over_d",
            ok=ld <= cfg.ld_max,
            value=ld,
            threshold=f"<= {cfg.ld_max}",
            message="L/D implausible (integration error?)",
            failure_class="NON_PHYSICAL",
        )
    )
    sign = expected_lift_sign(params, cfg)
    if sign == 0:
        checks.append(
            Check(name="lift_sign", ok=True, severity="skipped", message="geometry near zero lift; sign check skipped")
        )
    else:
        # race-car Cl = -(upright Cl): downforce geometry must give negative Cl
        ok = (cl < 0) == (sign > 0)
        checks.append(
            Check(
                name="lift_sign",
                ok=ok,
                value=cl,
                threshold="Cl<0" if sign > 0 else "Cl>0",
                message="Cl sign contradicts geometry (flipped convention?)",
                failure_class="NON_PHYSICAL",
            )
        )
    if result.fidelity == "neuralfoil":
        conf = result.confidence if result.confidence is not None else 0.0
        checks.append(
            Check(
                name="surrogate_confidence",
                ok=conf >= cfg.surrogate_confidence_min,
                value=conf,
                threshold=f">= {cfg.surrogate_confidence_min}",
                message="geometry out of NeuralFoil's distribution; escalate to XFoil",
                failure_class="NUMERICAL_FAILURE",
            )
        )
    for name in ("residuals", "mesh", "yplus"):
        checks.append(Check(name=name, ok=True, severity="skipped", message=f"not applicable at {result.fidelity}"))

    # Fidelity gap: same candidate, other tier, converged.
    others = [
        r.result
        for r in ledger
        if r.params.cid == params.cid
        and r.result.fidelity != result.fidelity
        and r.result.cl is not None
        and math.isfinite(r.result.cl)
    ]
    if others:
        gap = max(abs(o.cl - cl) for o in others)
        checks.append(
            Check(
                name="fidelity_gap",
                ok=gap < cfg.fidelity_gap_max,
                value=gap,
                threshold=f"< {cfg.fidelity_gap_max}",
                severity="suspect",
                message="tiers disagree (model-form error, e.g. XFoil near stall)",
            )
        )

    fatal = next((c for c in checks if not c.ok and c.severity == "fatal"), None)
    suspect = any(not c.ok and c.severity == "suspect" for c in checks)
    target = in_target(result, spec)
    if result.lower_fidelity:
        checks.append(
            Check(
                name="lower_fidelity",
                ok=True,
                severity="suspect",
                value=result.fallback_from,
                message=f"fallback result (requested {result.fallback_from}); cannot terminate the run as target_met",
            )
        )
    terminal = (
        target
        and not suspect
        and fatal is None
        and not result.lower_fidelity
        and result.fidelity in TERMINAL_FIDELITIES
    )
    return NumericReport(
        checks=checks,
        failure_class=fatal.failure_class if fatal else None,
        target_met=target,
        terminal=terminal,
        suspect=suspect,
    )


def suggest_diagnosis(result: CFDResult | None, spec: DesignSpec, parent: CFDResult | None = None) -> Diagnosis:
    """Deterministic physical diagnosis from solver facts. A starting point for the Critic."""
    if result is None or result.cl is None or result.cd is None:
        return Diagnosis(symptom="NONE", evidence=["no converged coefficients"])
    if bad := nonfinite_fields(result):
        return Diagnosis(symptom="NONE", evidence=[f"non-finite solver output: {', '.join(bad)}"])
    ev = []
    bl = result.bl
    if bl and bl.te_separation_xc is not None:
        ev.append(f"Cf<0 on suction side from x/c={bl.te_separation_xc:.2f} to the TE ({result.fidelity})")
        if parent and parent.cd and parent.cl:
            ev.append(f"Cd {parent.cd:.4f}→{result.cd:.4f}, Cl {parent.cl:.3f}→{result.cl:.3f} vs parent")
        if bl.te_separation_xc < 0.5:
            return Diagnosis(symptom="EARLY_STALL", x_over_c=(bl.te_separation_xc, 1.0), evidence=ev)
        return Diagnosis(symptom="TE_SEPARATION_MAIN", x_over_c=(bl.te_separation_xc, 1.0), evidence=ev)
    need_more = abs(result.cl) < abs(spec.target_cl) - spec.cl_tol
    if result.cd > spec.cd_max:
        ev.append(f"Cd={result.cd:.4f} > cd_max={spec.cd_max}")
        if bl and bl.bubbles:
            ev.append("laminar bubble(s) at x/c " + ", ".join(f"{a:.2f}-{b:.2f}" for a, b in bl.bubbles))
        return Diagnosis(symptom="EXCESS_PRESSURE_DRAG", evidence=ev)
    if need_more:
        ev.append(f"|Cl|={abs(result.cl):.3f} < |target|={abs(spec.target_cl):.3f}")
        return Diagnosis(symptom="INSUFFICIENT_LOADING", evidence=ev)
    if bl and bl.bubbles:
        ev.append(
            "laminar bubble(s) at x/c "
            + ", ".join(f"{a:.2f}-{b:.2f}" for a, b in bl.bubbles)
            + " (reattached; not TE separation)"
        )
    return Diagnosis(symptom="NONE", evidence=ev)
