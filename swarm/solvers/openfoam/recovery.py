"""OpenFOAM recovery ladder (milestone 5 part 2; BLUEPRINT §3 Scenario B).

A failed of2d solve is classified from the monitor's signature and the CFD agent (swarm.agents.cfd) picks the
next level. Code enforces what the agent cannot: levels are never repeated, the ladder is bounded (L5 ends it),
and every level is a bounded change of the L0 setup (SolverOverrides / MeshSpec), never a file or a command.

| level | action |
|---|---|
| L1 | lower relaxation: U 0.7 -> 0.5, p 0.3 -> 0.2, turbulence 0.7 -> 0.5 |
| L2 | first-order upwind for U for 300 iterations, then restart second order from that field |
| L3 | potentialFoam initial field and conservative freestream turbulence (viscosity ratio 1) |
| L4 | re-mesh: first cell x4 (lower aspect ratio), growth 1.10, normal smoothing x8, far field 50 c |
| L5 | drop fidelity: evaluate at XFoil and mark the design "unsimulatable at of2d" |

Classification (BLUEPRINT): a failure before iteration 50, or of the mesh itself, points at the mesh or the
boundary conditions (re-mesh); a later one at relaxation or schemes (numerics); persistent bounding of k or
omega at the turbulence initialisation or the near-wall mesh (re-initialise). After a checkMesh failure only L4
and L5 are allowed: L1-L3 change the solver, not the mesh, so they cannot change the outcome.
"""

from __future__ import annotations

import dataclasses
from typing import Literal

from swarm.solvers.openfoam.case import SolverOverrides
from swarm.solvers.openfoam.mesh import MeshSpec
from swarm.solvers.openfoam.monitor import iteration_of

MAX_LEVEL = 5
LEVELS: dict[int, str] = {
    1: "lower relaxation (U 0.5, p 0.2, turbulence 0.5)",
    2: "first-order U for 300 iterations, then second order from that field",
    3: "potentialFoam initialisation, conservative freestream turbulence",
    4: "re-mesh: first cell x4, growth 1.10, normal smoothing x8, far field 50 c",
    5: "drop fidelity to XFoil (unsimulatable at of2d)",
}
FailureClass = Literal["mesh", "numerics", "turbulence", "unknown"]
EARLY_ITER = 50
# Deterministic preference per failure class (the CFD agent's fallback, and the mock's policy).
PREFERENCE: dict[str, tuple[int, ...]] = {
    "mesh": (4, 1, 3, 2, 5),
    "numerics": (1, 2, 3, 4, 5),
    "turbulence": (3, 1, 4, 2, 5),
    "unknown": (1, 3, 4, 2, 5),
}


def classify(signature: str | None, status: str) -> FailureClass:
    sig = signature or ""
    if status == "mesh_failed" or sig.startswith("checkMesh"):
        return "mesh"
    if sig.startswith("persistent_bounding"):
        return "turbulence"
    it = iteration_of(sig)
    if it is not None:
        return "mesh" if it < EARLY_ITER else "numerics"
    if sig.startswith("timeout") or status in ("not_converged", "unsteady"):
        return "numerics"
    return "unknown"


def default_level(signature: str | None, status: str, tried: list[int]) -> int | None:
    """The first allowed level in the class's preference order; None when the ladder is exhausted."""
    for lvl in PREFERENCE[classify(signature, status)]:
        if next_level_allowed(lvl, tried, status):
            return lvl
    return None


def apply_level(level: int, base: SolverOverrides, mesh: MeshSpec) -> tuple[SolverOverrides, MeshSpec]:
    """The (overrides, mesh) for a ladder level, as bounded changes of the base setup. L5 is not a solve."""
    if level == 1:
        return base.model_copy(update={"relax_U": 0.5, "relax_p": 0.2, "relax_turb": 0.5}), mesh
    if level == 2:
        return base.model_copy(update={"first_order_iters": 300}), mesh
    if level == 3:
        return base.model_copy(update={"potential_init": True, "viscosity_ratio": 1.0}), mesh
    if level == 4:
        m = dataclasses.replace(
            mesh,
            first_cell=min(mesh.first_cell * 4, 2e-4),
            growth=min(mesh.growth, 1.10),
            # x2 left the bad_mesh case at 90 deg non-orthogonality; x8 gives 42 (docs/OPENFOAM_RECOVERY.md)
            smoothing=mesh.smoothing * 8,
            farfield=min(mesh.farfield, 50.0),
            max_step=min(mesh.max_step, 2.0),
        )
        return base, m
    raise ValueError(f"level {level} has no solver setup (L5 drops fidelity)")


MESH_LEVELS = (4, 5)  # the only levels that can change a checkMesh failure


def next_level_allowed(level: int, tried: list[int], status: str = "diverged") -> bool:
    if not (1 <= level <= MAX_LEVEL) or level in tried:
        return False
    return level in MESH_LEVELS if status == "mesh_failed" else True
