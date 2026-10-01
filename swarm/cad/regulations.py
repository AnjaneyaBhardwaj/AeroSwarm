"""Formula Student 2026 v1.1 regulation checks (BLUEPRINT §2).

Every check runs on outlines already scaled to mm and placed in the car frame
(x rearward, z up from the ground) at the mount point; see
`swarm.cad.build.placed_mm`. Each violation string names its rule and is
returned verbatim to the CAD agent.
"""

from __future__ import annotations

import numpy as np

from swarm.state import ReferenceCar, WingParams

FS2026 = {  # Formula Student Rules 2026 v1.1
    "T8.2.1_rear_max_height_mm": 1100,
    "T8.2.1_forward_max_height_mm": 500,
    "T8.2.3_max_behind_rear_tire_mm": 250,
    "T2.2.1_min_ground_clearance_mm": 30,
    "T2.4.1_min_radius_forward_mm": 3.0,
    "T2.4.1_min_radius_other_mm": 1.0,
}

NACA4_LE_RADIUS_COEFF = 1.1019  # r_LE ≈ 1.1019 t² c


def le_radius_mm(thickness: float, chord_mm: float) -> float:
    return NACA4_LE_RADIUS_COEFF * thickness**2 * chord_mm


def min_thickness_for_le_radius(chord_mm: float, r_min: float = FS2026["T2.4.1_min_radius_forward_mm"]) -> float:
    return float(np.sqrt(r_min / (NACA4_LE_RADIUS_COEFF * chord_mm)))


def check_regulations(elements: dict[str, np.ndarray], params: WingParams, car: ReferenceCar) -> list[str]:
    """elements: outlines placed in the car frame (mm). Returns violations."""
    pts = np.vstack(list(elements.values()))
    v = []
    top = float(pts[:, 1].max())
    if top >= FS2026["T8.2.1_rear_max_height_mm"]:
        v.append(f"T8.2.1: rear wing top at {top:.0f} mm; must be lower than 1100 mm")
    bottom = float(pts[:, 1].min())
    if bottom < FS2026["T2.2.1_min_ground_clearance_mm"]:
        v.append(f"T2.2.1: lowest point {bottom:.0f} mm is below the 30 mm ground clearance")
    rear = float(pts[:, 0].max())
    limit = car.rear_tire_rear_x + FS2026["T8.2.3_max_behind_rear_tire_mm"]
    if rear > limit:
        v.append(f"T8.2.3: wing extends {rear - car.rear_tire_rear_x:.0f} mm behind the rear tires (max 250 mm)")
    fwd = pts[pts[:, 0] < car.head_restraint_x]
    if len(fwd) and fwd[:, 1].max() >= FS2026["T8.2.1_forward_max_height_mm"]:
        v.append("T8.2.1: parts forward of the head-restraint plane must be below 500 mm")
    main = elements["main"]
    te_mm = float(np.hypot(*(main[0] - main[-1])))
    if te_mm < 2 * FS2026["T2.4.1_min_radius_other_mm"]:
        v.append(f"T2.4.1: main-plane TE thickness {te_mm:.1f} mm < 2 mm (needs a 1 mm edge radius)")
    r_le = le_radius_mm(params.main_thickness, car.chord_mm * (1 - params.flap_chord_ratio))
    if r_le < FS2026["T2.4.1_min_radius_forward_mm"]:
        t_min = min_thickness_for_le_radius(car.chord_mm * (1 - params.flap_chord_ratio))
        v.append(f"T2.4.1: main-plane LE radius {r_le:.1f} mm < 3 mm; increase main_thickness to at least {t_min:.4f}")
    return v
