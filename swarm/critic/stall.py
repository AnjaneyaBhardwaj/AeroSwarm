"""Stall-margin probe: re-solve a would-be-final design at alpha+1 and alpha+2 deg.

Same geometry, same fidelity (XFoil), same recovery ladder per probe point: levels
are tried in order from L0, each once, via `xfoil.next_level`. If the ladder is
exhausted or the output is non-finite the margin cannot be established, and a design
without a margin never ends the run. The slope threshold is `ValidatorConfig`'s
`stall_min_dcl_dalpha`.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from swarm.critic.numeric import VALIDATION, ValidatorConfig
from swarm.solvers import xfoil
from swarm.state import CFDResult, StallMargin

Solve = Callable[[float, int], CFDResult]  # (alpha_deg, ladder level) -> result


def _solve_ladder(solve: Solve, alpha: float) -> tuple[CFDResult | None, str]:
    tried: list[int] = []
    sig = "no_result"
    while (lvl := xfoil.next_level(tried)) is not None:
        r = solve(alpha, lvl)
        if r.status == "converged" and r.cl is not None and math.isfinite(r.cl):
            return r, ""
        sig = r.failure_signature or r.status
        tried.append(lvl)
    return None, f"ladder exhausted ({sig})"


def measure_stall_margin(
    base: CFDResult, alpha_deg: float, solve: Solve, cfg: ValidatorConfig = VALIDATION
) -> StallMargin:
    """`base` is the converged design-point result; `solve` re-runs it at another alpha."""
    alphas = [alpha_deg] + [round(alpha_deg + d, 4) for d in cfg.stall_probe_deg]
    cls: list[float | None] = [base.cl]
    levels: list[int | None] = [base.solver_level]
    seps: list[float | None] = [base.bl.te_separation_xc if base.bl else None]
    failure = None
    for a, d in zip(alphas[1:], cfg.stall_probe_deg, strict=True):
        r, why = _solve_ladder(solve, a)
        if r is None:
            cls.append(None)
            levels.append(None)
            seps.append(None)
            failure = failure or f"alpha+{d:g}: {why}"
            continue
        cls.append(r.cl)
        levels.append(r.solver_level)
        seps.append(r.bl.te_separation_xc if r.bl else None)
    # Race-car Cl is negative downforce; the slope is of downforce growth, d|Cl|/dalpha.
    pts = [(a, abs(c)) for a, c in zip(alphas, cls, strict=True) if c is not None]
    slopes = [(c1 - c0) / (a1 - a0) for (a0, c0), (a1, c1) in zip(pts, pts[1:], strict=False)]
    margin = min(slopes) if failure is None and slopes else None
    ok = margin is not None and margin >= cfg.stall_min_dcl_dalpha
    return StallMargin(
        alphas_deg=alphas,
        cls=cls,
        levels=levels,
        te_separation_xc=seps,
        slopes=[round(v, 5) for v in slopes],
        dcl_dalpha=None if margin is None else round(margin, 5),
        threshold=cfg.stall_min_dcl_dalpha,
        ok=ok,
        failure=failure,
    )
