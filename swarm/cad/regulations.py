"""Rulebook checks for the rear wing section (BLUEPRINT §2).

Every check runs on outlines already scaled to mm and placed in the car frame
(x rearward, z up from the ground) at the mount point; see
`swarm.cad.build.placed_mm`. Each violation string names its rule and is
returned verbatim to the CAD agent.

Rulebooks (`DesignSpec.rulebook`):
- "FSAE2027_v1.0" (default): Formula SAE Rules 2027 v1.0 (SAE International, 1 Sept 2026),
  docs/FSAE_Rules_2027_V1.pdf, section T.7 and V.1.4.
- "FS2026_v1.1": Formula Student Rules 2026 v1.1 (checked against search excerpts only; the
  official PDF was not reachable).

2D limits: the section is assumed inboard of the rear tyres (FSAE's Rear Aerodynamic Zone,
T.7.3.3) and its span is not checked (T.7.6 width; the 3D stage). End-plate (vertical) edges
are not modelled.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from swarm.state import ReferenceCar, WingParams


class Limit(BaseModel, frozen=True):
    value: float
    rule: str
    text: str  # what the rule says, for the violation message


class Rulebook(BaseModel, frozen=True):
    name: str
    rear_max_height: Limit  # behind the head-restraint plane (FSAE: in the Rear Aerodynamic Zone)
    heights_inclusive: bool  # True: "no higher than" (at the limit is legal); False: "lower than"
    forward_max_height: Limit  # forward of the head-restraint plane
    max_behind_rear_tire: Limit
    min_ground_clearance: Limit
    le_radius_min: Limit  # forward-facing horizontal edge = the wing's leading edge
    other_edge_radius_min: Limit  # trailing edge


RULEBOOKS: dict[str, Rulebook] = {
    "FSAE2027_v1.0": Rulebook(
        name="Formula SAE Rules 2027 v1.0",
        rear_max_height=Limit(value=1200, rule="T.7.7.1a", text="no higher than 1200 mm in the Rear Aerodynamic Zone"),
        heights_inclusive=True,
        forward_max_height=Limit(
            value=500, rule="T.7.7.1b", text="no higher than 500 mm outside the Rear Aerodynamic Zone"
        ),
        max_behind_rear_tire=Limit(value=250, rule="T.7.5b", text="no more than 250 mm rearward of the rear tires"),
        # V.1.4.1 has no number: nothing but the tires may touch the ground in dynamic events.
        min_ground_clearance=Limit(value=0, rule="V.1.4.1", text="must not touch the ground"),
        le_radius_min=Limit(
            value=5.0, rule="T.7.1.4", text="forward facing horizontal edges need a minimum radius of 5 mm"
        ),
        # T.7.1.5 says only "not sharp"; 1 mm radius (2 mm TE thickness) is the project's threshold.
        other_edge_radius_min=Limit(
            value=1.0, rule="T.7.1.5", text="other edges must not be sharp (project threshold: 1 mm radius)"
        ),
    ),
    "FS2026_v1.1": Rulebook(
        name="Formula Student Rules 2026 v1.1",
        rear_max_height=Limit(value=1100, rule="T8.2.1", text="must be lower than 1100 mm"),
        heights_inclusive=False,
        forward_max_height=Limit(
            value=500, rule="T8.2.1", text="parts forward of the head-restraint plane must be below 500 mm"
        ),
        max_behind_rear_tire=Limit(value=250, rule="T8.2.3", text="max 250 mm behind the rear tires"),
        min_ground_clearance=Limit(value=30, rule="T2.2.1", text="30 mm minimum ground clearance"),
        le_radius_min=Limit(value=3.0, rule="T2.4.1", text="forward facing edges need a minimum radius of 3 mm"),
        other_edge_radius_min=Limit(value=1.0, rule="T2.4.1", text="other edges need a minimum radius of 1 mm"),
    ),
}
DEFAULT_RULEBOOK = "FSAE2027_v1.0"

NACA4_LE_RADIUS_COEFF = 1.1019  # r_LE ≈ 1.1019 t² c


def le_radius_mm(thickness: float, chord_mm: float) -> float:
    return NACA4_LE_RADIUS_COEFF * thickness**2 * chord_mm


def min_thickness_for_le_radius(chord_mm: float, rulebook: str = DEFAULT_RULEBOOK) -> float:
    """Thinnest NACA 4-digit section whose leading-edge radius meets the rulebook's minimum."""
    return float(np.sqrt(RULEBOOKS[rulebook].le_radius_min.value / (NACA4_LE_RADIUS_COEFF * chord_mm)))


def check_regulations(
    elements: dict[str, np.ndarray], params: WingParams, car: ReferenceCar, rulebook: str = DEFAULT_RULEBOOK
) -> list[str]:
    """elements: outlines placed in the car frame (mm). Returns violations, each naming its rule."""
    rb = RULEBOOKS[rulebook]
    pts = np.vstack(list(elements.values()))
    v = []
    top = float(pts[:, 1].max())
    lim = rb.rear_max_height
    if top > lim.value or (top == lim.value and not rb.heights_inclusive):
        v.append(f"{lim.rule}: rear wing top at {top:.0f} mm; {lim.text}")
    bottom = float(pts[:, 1].min())
    lim = rb.min_ground_clearance
    if bottom < lim.value or bottom <= 0:
        v.append(f"{lim.rule}: lowest point {bottom:.0f} mm; {lim.text}")
    rear = float(pts[:, 0].max())
    lim = rb.max_behind_rear_tire
    if rear > car.rear_tire_rear_x + lim.value:
        v.append(f"{lim.rule}: wing extends {rear - car.rear_tire_rear_x:.0f} mm behind the rear tires; {lim.text}")
    fwd = pts[pts[:, 0] < car.head_restraint_x]
    lim = rb.forward_max_height
    if len(fwd):
        h = float(fwd[:, 1].max())
        if h > lim.value or (h == lim.value and not rb.heights_inclusive):
            v.append(f"{lim.rule}: {h:.0f} mm forward of the head-restraint plane; {lim.text}")
    main = elements["main"]
    te_mm = float(np.hypot(*(main[0] - main[-1])))
    lim = rb.other_edge_radius_min
    if te_mm < 2 * lim.value:
        v.append(f"{lim.rule}: main-plane TE thickness {te_mm:.1f} mm < {2 * lim.value:g} mm; {lim.text}")
    chord = car.chord_mm * (1 - params.flap_chord_ratio)
    r_le = le_radius_mm(params.main_thickness, chord)
    lim = rb.le_radius_min
    if r_le < lim.value:
        t_min = min_thickness_for_le_radius(chord, rulebook)
        v.append(
            f"{lim.rule}: main-plane LE radius {r_le:.1f} mm < {lim.value:g} mm ({lim.text}); "
            f"increase main_thickness to at least {t_min:.4f}"
        )
    return v
