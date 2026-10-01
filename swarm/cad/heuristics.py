"""Curated symptom → lever table (BLUEPRINT §2, layer 2).

Each lever is (param, direction, mechanism). Direction is the sign of the
parameter change. The heuristics propose; the sensitivities decide.
"""

from __future__ import annotations

from pydantic import BaseModel


class Heuristic(BaseModel):
    param: str
    direction: int  # +1 increase, -1 decrease, 0 tune
    mechanism: str


HEURISTICS: dict[str, list[tuple[str, int, str]]] = {
    "TE_SEPARATION_FLAP": [
        ("flap_deflection_deg", -1, "reduce adverse pressure gradient on flap"),
        ("slot_gap", +1, "stronger slot flow helps the flap boundary layer; optimum is geometry-specific"),
        ("slot_overlap", 0, "tune toward slightly positive overlap for slot effect"),
    ],
    "TE_SEPARATION_MAIN": [
        ("main_camber_pos", -1, "move camber forward, unload the aft region"),
        ("alpha_deg", -1, "reduce overall loading"),
    ],
    "EARLY_STALL": [
        ("alpha_deg", -1, "back away from stall"),
        ("main_thickness", +1, "thicker section delays leading-edge stall"),
    ],
    "LE_SUCTION_SPIKE": [
        ("main_thickness", +1, "larger LE radius softens the suction peak"),
        ("alpha_deg", -1, "lower incidence reduces the leading-edge suction peak"),
    ],
    "INSUFFICIENT_LOADING": [
        ("main_camber", +1, "more camber raises loading at fixed incidence"),
        ("alpha_deg", +1, "more incidence raises loading"),
        ("gurney_h", +1, "cheap Cl gain, costs Cd"),
        ("flap_deflection_deg", +1, "more flap deflection raises aft loading"),
    ],
    "EXCESS_PRESSURE_DRAG": [
        ("main_thickness", -1, "thinner section cuts pressure drag"),
        ("alpha_deg", -1, "lower incidence trims the separated wake"),
        ("main_camber_pos", -1, "forward camber eases the aft pressure recovery"),
    ],
}


def lookup_heuristics(symptom: str, allowed: tuple[str, ...] | list[str] | None = None) -> list[Heuristic]:
    rows = [Heuristic(param=p, direction=d, mechanism=m) for p, d, m in HEURISTICS.get(symptom, [])]
    if allowed is not None:
        rows = [h for h in rows if h.param in allowed]
    return rows
