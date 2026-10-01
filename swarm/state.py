"""State schemas (BLUEPRINT §1). State is the single source of truth.

Sign convention: every Cl stored in a CFDResult is in the race-car frame,
i.e. NEGATIVE means downforce. Solvers simulate the upright section and
negate Cl (BLUEPRINT §4, "Downforce convention").
"""

from __future__ import annotations

import hashlib
import json
import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

Fidelity = Literal["neuralfoil", "xfoil", "of2d", "of3d"]
FIDELITY_RANK: dict[str, int] = {"neuralfoil": 0, "xfoil": 1, "of2d": 2, "of3d": 3}
# Fidelities whose result may terminate a run as target_met.
TERMINAL_FIDELITIES: frozenset[str] = frozenset({"xfoil", "of2d", "of3d"})

AIR_KINEMATIC_VISCOSITY = 1.5e-5  # m^2/s, rounded sea-level value (BLUEPRINT appendix)
SPEED_OF_SOUND = 340.3  # m/s, ISA sea level

# WingParams are quantized to this step before hashing (and before use), so
# the evaluated geometry is exactly the one the cid names.
PARAM_QUANTUM = 1e-4


class ReferenceCar(BaseModel, frozen=True):
    """Car frame: x rearward from the front axle, z up from the ground, mm."""

    chord_mm: float = 300.0  # physical chord, sets real edge radii and Re
    head_restraint_x: float  # rearmost face of head-restraint support
    rear_tire_rear_x: float  # rearmost point of the rear tires
    wing_mount_x: float  # x of the main-plane leading edge
    wing_mount_z: float  # height of the main-plane leading edge
    inner_rear_track_mm: float  # caps span for the 3D stage (T8.2.2)


# Placeholder geometry for a generic Formula Student car. These are NOT
# measurements of a real car; replace with your team's CAD numbers.
PLACEHOLDER_CAR = ReferenceCar(
    chord_mm=300.0,
    head_restraint_x=1350.0,
    rear_tire_rear_x=1850.0,
    wing_mount_x=1760.0,
    wing_mount_z=950.0,
    inner_rear_track_mm=1000.0,
)


class DesignSpec(BaseModel, frozen=True):
    """Immutable target; re-injected into every agent call."""

    model_config = ConfigDict(extra="forbid")  # Re is derived; passing `reynolds=` is an error

    component: Literal["wing_1el", "wing_2el", "diffuser"]
    target_cl: float  # e.g. -1.50 (downforce)
    cl_tol: float = 0.03
    cd_max: float
    speed_mps: float = Field(gt=0)  # sets Re together with car.chord_mm
    mach: float = 0.15  # informational; T0/T1 solvers run incompressible
    ncrit: float = Field(9.0, gt=0)  # e^N transition; 9 = XFoil's "average wind tunnel" [S3]
    max_evals: int = 80
    max_wall_hours: float = 4.0
    max_cost_usd: float | None = Field(None, gt=0)  # estimated LLM spend cap; None = uncapped
    rulebook: Literal["FS2026_v1.1", "none"] = "FS2026_v1.1"
    car: ReferenceCar = PLACEHOLDER_CAR

    @model_validator(mode="before")
    @classmethod
    def _reynolds_is_derived(cls, data: Any) -> Any:
        """Accept a dumped `reynolds` only if it matches speed × chord / ν (round-trips)."""
        if isinstance(data, dict) and "reynolds" in data:
            data = dict(data)
            given = data.pop("reynolds")
            car = data.get("car", PLACEHOLDER_CAR)
            chord = car["chord_mm"] if isinstance(car, dict) else car.chord_mm
            derived = data["speed_mps"] * (chord / 1000.0) / AIR_KINEMATIC_VISCOSITY
            if abs(float(given) - derived) > 1e-6 * derived:
                raise ValueError("reynolds is derived from speed_mps and car.chord_mm; set speed_mps instead")
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reynolds(self) -> float:
        """Chord Reynolds number, derived (never set independently)."""
        return self.speed_mps * (self.car.chord_mm / 1000.0) / AIR_KINEMATIC_VISCOSITY


def speed_for_reynolds(re: float, chord_mm: float) -> float:
    return re * AIR_KINEMATIC_VISCOSITY / (chord_mm / 1000.0)


class WingParams(BaseModel, frozen=True):
    main_camber: float = Field(ge=0.00, le=0.09)  # m (fraction of chord)
    main_camber_pos: float = Field(ge=0.20, le=0.60)
    main_thickness: float = Field(ge=0.08, le=0.18)
    alpha_deg: float = Field(ge=-2.0, le=14.0)
    flap_chord_ratio: float = Field(0.0, ge=0.0, le=0.45)  # 0 = single element
    flap_deflection_deg: float = Field(0.0, ge=0.0, le=45.0)
    slot_gap: float = Field(0.015, ge=0.005, le=0.06)  # fraction of chord; NASA 2-element tests used 3.1-6% [S6]
    slot_overlap: float = Field(0.0, ge=-0.01, le=0.07)  # same tests used 3.5-6.6% [S6]
    gurney_h: float = Field(0.0, ge=0.0, le=0.02)

    @model_validator(mode="before")
    @classmethod
    def _quantize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                k: quantize(v) if isinstance(v, float | int) and not isinstance(v, bool) else v for k, v in data.items()
            }
        return data

    @model_validator(mode="after")
    def _cross_constraints(self):
        if self.flap_chord_ratio == 0 and self.flap_deflection_deg > 0:
            raise ValueError("flap_deflection set but no flap element")
        return self

    @property
    def cid(self) -> str:
        """Content-addressed candidate id over the quantized parameters."""
        blob = json.dumps(self.model_dump(), sort_keys=True).encode()
        return hashlib.sha1(blob).hexdigest()[:10]

    @classmethod
    def bounds(cls) -> dict[str, tuple[float, float]]:
        out = {}
        for name, f in cls.model_fields.items():
            lo = hi = None
            for m in f.metadata:
                lo = getattr(m, "ge", lo)
                hi = getattr(m, "le", hi)
            out[name] = (float(lo), float(hi))
        return out


def quantize(v: float, q: float = PARAM_QUANTUM) -> float:
    return round(round(float(v) / q) * q, 10)


# Parameters a single-element wing may change. Flap/slot fields stay fixed.
SINGLE_ELEMENT_PARAMS = ("main_camber", "main_camber_pos", "main_thickness", "alpha_deg")


def free_params(spec: DesignSpec) -> tuple[str, ...]:
    if spec.component == "wing_1el":
        return SINGLE_ELEMENT_PARAMS
    return tuple(WingParams.model_fields)


class GeometryArtifact(BaseModel):
    cid: str
    step_paths: dict[str, str] = {}  # CadQuery/STEP export arrives with the OpenFOAM milestone
    stl_paths: dict[str, str] = {}
    coords_path: str  # 2D coords for XFoil/NeuralFoil (Selig .dat)
    checks: dict[str, bool]
    te_thickness: float  # fraction of chord
    violations: list[str] = []


class BoundaryLayerSummary(BaseModel):
    """Suction-side boundary-layer facts parsed from solver output."""

    suction_side: Literal["upper", "lower"] = "upper"  # in the upright solver frame
    cf_te: float | None = None  # suction-side Cf at the last surface station (TE)
    te_separation_xc: float | None = None  # Cf<0 from here persists to the TE
    bubbles: list[tuple[float, float]] = []  # reversed regions that reattach
    transition_xc: float | None = None
    source: Literal["xfoil_cf", "none"] = "none"


class CFDResult(BaseModel):
    cid: str
    fidelity: Fidelity
    status: Literal["converged", "diverged", "unsteady", "mesh_failed", "timeout", "not_converged"]
    cl: float | None = None  # race-car convention: negative = downforce
    cd: float | None = None
    cm: float | None = None
    residual_drop_orders: dict[str, float] = {}
    coeff_rel_std_window: dict[str, float] = {}
    yplus: tuple[float, float, float] | None = None
    mesh: dict = {}
    failure_signature: str | None = None
    log_path: str = ""
    plots: dict[str, str] = {}
    wall_s: float = 0.0
    # T0/T1 specifics
    confidence: float | None = None  # NeuralFoil analysis_confidence
    solver_level: int | None = None  # XFoil recovery-ladder level that produced this
    fallback_from: Fidelity | None = None  # set when this result replaced a failed tier
    bl: BoundaryLayerSummary | None = None
    artifacts: dict[str, str] = {}  # polar / dump / cp paths

    @property
    def lower_fidelity(self) -> bool:
        """A fallback result is lower fidelity than what was requested."""
        return self.fallback_from is not None


class Diagnosis(BaseModel):
    symptom: Literal[
        "TE_SEPARATION_MAIN",
        "TE_SEPARATION_FLAP",
        "LE_SUCTION_SPIKE",
        "SLOT_CHOKED",
        "EARLY_STALL",
        "INSUFFICIENT_LOADING",
        "EXCESS_PRESSURE_DRAG",
        "NONE",
    ]
    x_over_c: tuple[float, float] | None = None
    evidence: list[str] = []


class Finding(BaseModel):
    observation: str
    location: str
    source: Literal["numeric", "boundary_layer", "cp", "residuals", "contour", "streamlines"]
    consistent_with_numeric: bool
    severity: Literal["info", "suspect", "fatal"] = "info"


VerdictStatus = Literal["PASS", "NON_PHYSICAL", "NUMERICAL_FAILURE", "TARGET_MISS", "UNSTEADY"]


class Verdict(BaseModel):
    status: VerdictStatus
    diagnosis: Diagnosis
    findings: list[Finding] = []
    confidence: float = Field(ge=0.0, le=1.0)


class ParamChange(BaseModel):
    name: str
    new_value: float
    mechanism: str  # physical reasoning
    expected_dCl_sign: Literal[-1, 0, 1]  # sign of change in race-car Cl
    expected_dCd_sign: Literal[-1, 0, 1]


class ParamDelta(BaseModel):
    changes: list[ParamChange] = Field(min_length=1, max_length=3)
    note: str = ""  # e.g. a logged heuristic-vs-sensitivity contradiction


class StrategyMemo(BaseModel):
    hypothesis: str
    focus_params: list[str]
    trust_radius: float = Field(ge=0.02, le=0.5)
    fidelity: Fidelity
    mode: Literal["reasoned_step", "inner_optimizer"]
    inner_budget: int = 0
    promote_cid: str | None = None  # re-evaluate this ledger candidate at `fidelity`
    declare_plateau: bool = False


class StallMargin(BaseModel):
    """Stall-margin probe: the same candidate re-solved at alpha+1 and alpha+2 deg.

    `dcl_dalpha` is the smallest forward secant of downforce growth, d|Cl|/dalpha in
    1/deg (upright-section sign: positive = still loading up). Thin-airfoil theory is
    0.110/deg; a healthy attached section stays above ~0.08, and a slope near zero or
    negative means alpha+1..2 deg is at or past Cl,max.
    """

    alphas_deg: list[float]  # alpha, alpha+1, alpha+2 (race-car Cl in `cls`)
    cls: list[float | None]
    levels: list[int | None]  # XFoil ladder level that solved each point
    te_separation_xc: list[float | None] = []  # suction-side TE separation start at each point
    slopes: list[float] = []  # d|Cl|/dalpha between successive points
    dcl_dalpha: float | None = None  # min(slopes); None if a probe did not solve
    threshold: float
    ok: bool
    failure: str | None = None  # e.g. "alpha+2: ladder exhausted (not_converged@L3)"


class SurrogateScreen(BaseModel):
    """NeuralFoil-tier screen of one geometry: alpha, alpha+1, alpha+2 deg in one surrogate call.

    Stall: the same d|Cl|/dalpha definition as `StallMargin` (smallest forward secant,
    1/deg), on NeuralFoil's Cl. Separation: NeuralFoil's suction-side (upright upper surface)
    boundary-layer shape factor H at its last station (x/c 0.984); a warning when H there is
    at or above `h_sep`. `sep_xc` is where the run of H >= h_sep that reaches the TE starts.
    It gates promotion to XFoil; it never overrides an XFoil result (XFoil's gates stay
    authoritative). Thresholds: `ValidatorConfig.screen_*`.
    """

    alphas_deg: list[float]
    cls: list[float]  # race-car Cl (negative = downforce)
    slopes: list[float] = []  # d|Cl|/dalpha between successive points
    dcl_dalpha: float | None = None  # min(slopes)
    stall_threshold: float
    stall_ok: bool
    te_shape_factor: list[float] = []  # suction-side H at x/c 0.984, per alpha
    sep_xc: float | None = None  # at the design alpha
    h_sep: float
    sep_warning: bool  # at the design alpha
    ok: bool  # stall_ok and not sep_warning

    def reasons(self) -> list[str]:
        out = []
        if not self.stall_ok:
            v = "n/a" if self.dcl_dalpha is None else f"{self.dcl_dalpha:.3f}"
            out.append(f"NeuralFoil stall screen: d|Cl|/dalpha {v}/deg < {self.stall_threshold}")
        if self.sep_warning:
            h = self.te_shape_factor[0] if self.te_shape_factor else float("nan")
            out.append(f"NeuralFoil separation warning: suction-side H {h:.2f} >= {self.h_sep} at the TE")
        return out


class EvalRecord(BaseModel):
    generation: int
    params: WingParams
    result: CFDResult
    verdict: Verdict | None
    rationale: str  # CAD agent's stated mechanism
    quarantined: bool = False  # excluded from "best" (non-physical)
    predicted_signs: dict[str, tuple[int, int]] = {}  # param -> (dCl sign, dCd sign)
    parent_cid: str | None = None
    stall_margin: StallMargin | None = None  # measured only for a candidate that would otherwise be target_met
    screen: SurrogateScreen | None = None  # NeuralFoil screen of this geometry (any fidelity)
    failed_checks: list[str] = []  # names of the numeric checks that failed (not skipped ones)


class SwarmState(TypedDict, total=False):
    spec: DesignSpec
    run_dir: str
    generation: int
    strategy: StrategyMemo | None
    params: WingParams | None
    parent: WingParams | None
    delta: ParamDelta | None
    geometry: GeometryArtifact | None
    result: CFDResult | None
    numeric: Any  # critic.numeric.NumericReport
    stall: StallMargin | None  # stall-margin probe for the current candidate, when one was run
    screen: SurrogateScreen | None  # NeuralFoil screen of the current candidate
    sens: dict  # NeuralFoil sensitivities at the generation's base design
    solver: dict  # {"fidelity", "level", "tried", "fallback_from"} for the current candidate
    verdict: Verdict | None
    ledger: Annotated[list[EvalRecord], operator.add]  # append-only
    events: Annotated[list[dict], operator.add]  # audit trail
    retries: dict[str, int]  # {"cad": n, "xfoil_level": k}
    pending_violation: str | None
    termination: (
        Literal["target_met", "eval_budget", "wall_clock", "cost_cap", "plateau", "fatal", "invalid_llm", "unknown"]
        | None
    )
    started_at: float
