# The Multi-Agent Generative Aero-Optimization Swarm

**Technical blueprint + plain-language sample run**

An agentic AI system where autonomous LLM agents (orchestrated with LangGraph) collaboratively design, mesh, simulate, and iteratively optimize an automotive aerodynamic component (rear wing or rear diffuser) to hit drag (Cd) and lift (Cl) targets without human intervention.

---

## Table of Contents

- [Guiding Principle](#guiding-principle)
- **Part I: Technical Blueprint**
  - [1. Agent Topology & State Management](#1-agent-topology--state-management)
  - [2. Tool Registration & Tool-Calling Design](#2-tool-registration--tool-calling-design)
    - [Regulation compliance (Formula Student 2026)](#regulation-compliance-formula-student-2026)
  - [3. The Self-Correction & Reasoning Loop](#3-the-self-correction--reasoning-loop)
  - [4. Lightweight POC Architecture](#4-lightweight-poc-architecture)
  - [5. Portfolio & Repo Showcasing](#5-portfolio--repo-showcasing)
    - [Visualization](#visualization)
- **Part II: A Sample Run, Explained Simply**
  - [The Basics First](#the-basics-first)
  - [The Mission](#the-mission)
  - [Round-by-Round Walkthrough](#round-0-the-starting-point)
  - [What This Run Showed](#what-this-run-showed)
- [Appendix: where every number comes from](#appendix-where-every-number-comes-from)

---

## Guiding Principle

**The LLMs reason and the deterministic code executes.** Agents decide what to change and why. Typed tools, templates, validators, and a numerical optimizer do the geometry, meshing, solving, and number-crunching.

Systems that let an LLM freely write CadQuery scripts or shell commands look impressive in a demo, then fail on the third iteration. Reviewers at Tier-1 automotive groups will spot that immediately. Reviewers at AI labs will ask how you bounded the action space. Design for both audiences from day one.

---

# Part I: Technical Blueprint

## 1. Agent Topology & State Management

### Framework choice: LangGraph

Use LangGraph, not CrewAI or AutoGen.

- **You need a state machine, not a group chat.** Your control flow has hard branches: geometry invalid, solver diverged, target met, budget exhausted.
- **LangGraph gives you the right primitives.** It has typed state, conditional edges, per-node retry policies, and checkpointing that lets a crashed 6-hour run resume at the failed node.
- **Conversational frameworks cause context drift.** In CrewAI and AutoGen, agents read each other's prose. Drift is exactly the failure you're trying to prevent.

### Graph topology

LLM nodes are marked `[LLM]`. Everything else is deterministic Python.

```
START
  └─► chief_plan [LLM] ──────────────────────────────────────┐
        │  (StrategyMemo: hypothesis, param focus, fidelity) │
        ▼                                                    │
      cad_propose [LLM] ◄──────────┐                         │
        │  (ParamDelta, bounded)   │ violations (≤3 tries)   │
        ▼                          │                         │
      geometry_build+validate ─────┘                         │
        │ ok                                                 │
        ▼                                                    │
      cfd_setup ──► cfd_mesh ──► cfd_solve                   │
        ▲               │           │ (live residual monitor)│
        │ recovery      ▼           ▼                        │
      cfd_recover [LLM-bounded] ◄── numeric_validate         │
                                    │                        │
                                    ▼                        │
                              critic [LLM + vision]          │
                                    │                        │
          ┌────────────┬────────────┼──────────────┐         │
       PASS+target  NON_PHYSICAL  NUMERICAL     TARGET_MISS ─┘
          │          → cad_propose → cfd_recover
          ▼
       report ──► END   (also reached when the budget is exhausted: best-so-far)
```

### Agent definitions

Every agent's output is a Pydantic schema enforced through structured output or tool calling. No agent ever returns free prose that another agent parses.

#### Chief Aerodynamicist (strategist)

It owns the search strategy. It does not touch geometry or solver settings.

```text
You are the Chief Aerodynamicist leading an autonomous optimization of a {component}
for a race car. Downforce is NEGATIVE lift. Target: Cl = {target_cl} ± {tol},
Cd ≤ {cd_max}, at Re = {re:.2e}, M = {mach}.

You receive: the immutable DesignSpec, a compressed ledger (best 5, last 5,
failure table), local sensitivities dCl/dp and dCd/dp, and the Critic's latest verdict.

Your job each generation:
1. State ONE falsifiable hypothesis about what limits performance
   (e.g., "flap is separating; lift is capped by aft loading, not camber").
2. Choose which ≤3 parameters to explore and a trust-region radius (fraction of range).
3. Choose fidelity: neuralfoil | xfoil | of2d. Promote only candidates that won the lower tier.
4. Decide whether to hand the next K evaluations to the numerical optimizer (inner loop)
   or to direct a single reasoned move.

Never invent performance numbers. Every number you cite must come from the ledger.
If three consecutive hypotheses fail to improve the objective, widen exploration
or declare a plateau.
Output: StrategyMemo.
```

#### CAD Generative Agent (geometry translator)

It converts diagnoses into bounded parameter deltas.

```text
You are a CAD engineer operating a parametric wing generator. You do NOT write
geometry code. You modify a typed parameter vector.

Inputs: current WingParams, parameter bounds, the Critic's structured diagnosis
(symptom, chordwise location, evidence), sensitivities, and relevant entries
from the design-heuristics table.

Rules:
- Change at most the parameters the Chief allowed, within the trust region.
- Each change needs a physical mechanism (e.g., "open slot gap 1.2%→1.6% c to
  re-energize the flap boundary layer") and the expected sign of ΔCl and ΔCd,
  consistent with the sensitivities. If the sensitivities contradict your
  heuristic, say so and follow the sensitivities.
- If a previous proposal was rejected, read the violation and fix exactly that.
Output: ParamDelta.
```

#### CFD Automation Agent (numerics operator)

In normal operation it is mostly deterministic. Its LLM is only invoked for recovery decisions.

```text
You are a CFD engineer. Cases are generated from validated templates; you may only
set fields of SolverOverrides (bounded relaxation factors, scheme choices from an
enum, mesh refinement levels, layer settings, iteration counts).

When a run fails you receive: failure signature, iteration of failure, offending
field, last residual history (summarized), checkMesh summary, and which recovery
levels were already tried. Choose the next recovery action from the ladder
and justify it from the evidence. Never retry an identical configuration.
Output: RecoveryAction.
```

#### Engineering Critic (verifier)

It is the only agent allowed to declare a result valid, and it must be grounded in numbers.

```text
You are an independent verification engineer. Your default stance is skeptical.
You receive: numeric validator results (hard facts), coefficient histories,
and rendered images (Cp distribution vs. previous best, residual plot,
pressure contour near TE/slot, streamlines).

Rules:
- Numeric validators are authoritative. Visual evidence may DOWNGRADE a
  result (PASS→SUSPECT/FAIL) but may never UPGRADE a failed numeric check.
- Each finding must cite an observation, a location (x/c or region),
  and whether it is consistent with the numeric data.
- Classify: PASS | NON_PHYSICAL | NUMERICAL_FAILURE | TARGET_MISS | UNSTEADY.
- For TARGET_MISS, produce a physical diagnosis (symptom enum + location), not a fix.
Output: Verdict.
```

The Critic diagnoses and the CAD agent prescribes. Keeping those roles separate stops one model from confirming its own ideas.

### Global state

The core rule is that **state is the single source of truth, and messages are disposable.** Each LLM node builds its prompt fresh from state through a role-specific `brief_for(role, state)` function. No agent reads another agent's chat history.

```python
# swarm/state.py
from __future__ import annotations
import hashlib, json, operator
from typing import Annotated, Literal, TypedDict
from pydantic import BaseModel, Field, model_validator

Fidelity = Literal["neuralfoil", "xfoil", "of2d", "of3d"]

class DesignSpec(BaseModel, frozen=True):           # immutable, re-injected every call
    component: Literal["wing_1el", "wing_2el", "diffuser"]
    target_cl: float                                # e.g. -1.50 (downforce)
    cl_tol: float = 0.03
    cd_max: float
    reynolds: float                                 # 0.25 m chord @ 50 m/s ≈ 8.3e5
    mach: float = 0.15
    max_evals: int = 80
    max_wall_hours: float = 4.0
    rulebook: Literal["FS2026_v1.1", "none"] = "FS2026_v1.1"   # see "Regulation compliance"
    car: "ReferenceCar | None" = None               # needed to place the wing inside the rule box

class ReferenceCar(BaseModel, frozen=True):         # car frame: x rearward, z up from ground, mm
    chord_mm: float = 300.0                         # physical chord, sets real edge radii
    head_restraint_x: float                         # rearmost face of head-restraint support
    rear_tire_rear_x: float                         # rearmost point of the rear tires
    wing_mount_z: float                             # height of the main-plane leading edge
    inner_rear_track_mm: float                      # caps span for the 3D stage (T8.2.2)

class WingParams(BaseModel, frozen=True):
    main_camber: float = Field(ge=0.00, le=0.09)    # m (fraction of chord)
    main_camber_pos: float = Field(ge=0.20, le=0.60)
    main_thickness: float = Field(ge=0.08, le=0.18)
    alpha_deg: float = Field(ge=-2.0, le=14.0)
    flap_chord_ratio: float = Field(ge=0.0, le=0.45)  # 0 = single element
    flap_deflection_deg: float = Field(ge=0.0, le=45.0)
    slot_gap: float = Field(ge=0.005, le=0.06)        # fraction of chord; NASA 2-element tests used 3.1–6% [S6]
    slot_overlap: float = Field(ge=-0.01, le=0.07)    # same tests used 3.5–6.6% [S6]; optimizer finds the optimum
    gurney_h: float = Field(ge=0.0, le=0.02)

    @model_validator(mode="after")
    def _cross_constraints(self):
        if self.flap_chord_ratio == 0 and self.flap_deflection_deg > 0:
            raise ValueError("flap_deflection set but no flap element")
        return self

    @property
    def cid(self) -> str:                           # content-addressed candidate id
        blob = json.dumps(self.model_dump(), sort_keys=True).encode()
        return hashlib.sha1(blob).hexdigest()[:10]

class GeometryArtifact(BaseModel):
    cid: str
    step_paths: dict[str, str]                      # {"main": ..., "flap": ...}
    stl_paths: dict[str, str]
    coords_path: str                                # 2D coords for XFoil/NeuralFoil
    checks: dict[str, bool]                         # valid_solid, watertight, no_intersection, min_gap_ok...
    te_thickness: float

class CFDResult(BaseModel):
    cid: str
    fidelity: Fidelity
    status: Literal["converged", "diverged", "unsteady", "mesh_failed", "timeout", "not_converged"]
    cl: float | None = None
    cd: float | None = None
    cm: float | None = None
    residual_drop_orders: dict[str, float] = {}     # {"p": 4.2, "Ux": 5.1, ...}
    coeff_rel_std_window: dict[str, float] = {}     # last-N-iteration stability
    yplus: tuple[float, float, float] | None = None # min / mean / max
    mesh: dict = {}                                 # cells, maxNonOrtho, maxSkewness, checkMesh_ok
    failure_signature: str | None = None            # "FPE@it37:omega", "bounding_k", ...
    log_path: str = ""
    plots: dict[str, str] = {}                      # role → PNG path
    wall_s: float = 0.0

class Diagnosis(BaseModel):
    symptom: Literal["TE_SEPARATION_MAIN", "TE_SEPARATION_FLAP", "LE_SUCTION_SPIKE",
                     "SLOT_CHOKED", "EARLY_STALL", "INSUFFICIENT_LOADING",
                     "EXCESS_PRESSURE_DRAG", "NONE"]
    x_over_c: tuple[float, float] | None
    evidence: list[str]

class Verdict(BaseModel):
    status: Literal["PASS", "NON_PHYSICAL", "NUMERICAL_FAILURE", "TARGET_MISS", "UNSTEADY"]
    diagnosis: Diagnosis
    findings: list[dict]                            # {observation, location, consistent_with_numeric}
    confidence: float

class EvalRecord(BaseModel):
    generation: int
    params: WingParams
    result: CFDResult
    verdict: Verdict | None
    rationale: str                                  # CAD agent's stated mechanism
    quarantined: bool = False                       # excluded from "best" (non-physical)

class StrategyMemo(BaseModel):
    hypothesis: str
    focus_params: list[str]
    trust_radius: float = Field(ge=0.02, le=0.5)
    fidelity: Fidelity
    mode: Literal["reasoned_step", "inner_optimizer"]
    inner_budget: int = 0

class SwarmState(TypedDict):
    spec: DesignSpec
    generation: int
    strategy: StrategyMemo | None
    params: WingParams | None
    geometry: GeometryArtifact | None
    result: CFDResult | None
    verdict: Verdict | None
    ledger: Annotated[list[EvalRecord], operator.add]   # append-only
    events: Annotated[list[dict], operator.add]         # audit trail (errors, recoveries, routing)
    retries: dict[str, int]                              # {"cad": n, "cfd_recovery": level}
    pending_violation: str | None                        # fed back to the CAD agent verbatim
    termination: Literal["target_met", "eval_budget", "wall_clock", "cost_cap", "plateau", "fatal", "invalid_llm", "unknown"] | None
```

### Anti-drift rules

These rules are what make long runs stable.

1. **Artifacts are passed by reference.** STEP/STL files, OpenFOAM logs, and images live on disk under `runs/<run_id>/<cid>/`. State holds paths plus parsed summaries. A raw 40 MB `log.simpleFoam` never enters a prompt; its parsed `CFDResult` does.
2. **The spec is frozen and re-injected into every call.** The target cannot erode ("maybe Cl = −1.3 is fine") because no agent can write to `spec`.
3. **The ledger is compressed per role.** `brief_for("chief")` renders the top 5 by objective, the last 5, and a failure table as a compact Markdown table. The CAD agent sees only the current candidate, the diagnosis, and the relevant heuristics. Each agent gets the smallest context that lets it do its job.
4. **Numbers only come from tools.** The report node composes results from `ledger`. It never paraphrases agent prose, so hallucinated performance claims have nowhere to enter.
5. **Candidate IDs are content-addressed.** `WingParams.cid` deduplicates proposals and caches evaluations. The CAD agent can't loop on the same design, because a duplicate `cid` is rejected with "already evaluated: Cl=…, Cd=…".
6. **Runs are checkpointed.**

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver   # pip install langgraph-checkpoint-sqlite

builder = StateGraph(SwarmState)
# ... add nodes / edges (Section 3) ...
with SqliteSaver.from_conn_string(f"runs/{run_id}/ckpt.db") as cp:
    app = builder.compile(checkpointer=cp)
    app.invoke(init_state, config={"configurable": {"thread_id": run_id},
                                   "recursion_limit": 1000})   # explicit cap; LangGraph 1.x defaults to 10007 [S10]
```

---

## 2. Tool Registration & Tool-Calling Design

### CAD agent tools

| Tool | Signature | Purpose |
|---|---|---|
| `get_current_design` | `() -> WingParams + bounds` | Read-only view of the current vector |
| `get_sensitivities` | `(params: list[str]) -> dict[param, {dCl, dCd}]` | Central finite differences on NeuralFoil (milliseconds each), which grounds the agent's intuition in gradients |
| `lookup_heuristics` | `(symptom: str) -> list[Heuristic]` | Retrieval over a curated symptom→lever table |
| `propose_delta` | `(delta: ParamDelta) -> ProposalResult` | The only mutating tool. It validates bounds, trust region, and duplicate `cid`, then builds the geometry |
| `render_preview` | `(cid) -> png` | Section overlay against the previous best, for the Critic and the README |

`ParamDelta` carries per-parameter justification:

```python
class ParamChange(BaseModel):
    name: str
    new_value: float
    mechanism: str                     # physical reasoning
    expected_dCl_sign: Literal[-1, 0, 1]
    expected_dCd_sign: Literal[-1, 0, 1]

class ParamDelta(BaseModel):
    changes: list[ParamChange] = Field(min_length=1, max_length=3)
```

Storing the expected signs lets you score the agent's physical reasoning afterwards: what fraction of predicted signs were correct. That metric is portfolio material.

### Translating feedback into geometry

This is a three-layer pipeline. The LLM only operates in the middle layer.

**Layer 1: the Critic produces a structured diagnosis.** "Reduce flow separation at the trailing edge" arrives as:

```json
{"symptom": "TE_SEPARATION_FLAP", "x_over_c": [0.82, 1.0],
 "evidence": ["Cp plateau on flap suction side from x/c=0.82",
              "Cd rose 18% vs parent while |Cl| rose 2%"]}
```

**Layer 2: the CAD agent selects levers.** It combines the diagnosis with the heuristics table and the sensitivities:

```python
HEURISTICS = {
  "TE_SEPARATION_FLAP": [
    ("flap_deflection_deg", -1, "reduce adverse pressure gradient on flap"),
    ("slot_gap", +1, "stronger slot flow helps the flap boundary layer; optimum is geometry-specific"),
    ("slot_overlap", 0, "tune toward slightly positive overlap for slot effect"),
  ],
  "TE_SEPARATION_MAIN": [
    ("main_camber_pos", -1, "move camber forward, unload the aft region"),
    ("alpha_deg", -1, "reduce overall loading"),
  ],
  "LE_SUCTION_SPIKE": [("main_thickness", +1, "larger LE radius softens the suction peak"),
                        ("alpha_deg", -1, "")],
  "INSUFFICIENT_LOADING": [("main_camber", +1, ""), ("gurney_h", +1, "cheap Cl gain, costs Cd"),
                           ("flap_deflection_deg", +1, "")],
}
```

The heuristics propose and the sensitivities decide. If the gradients show opening the slot hurts at this operating point, the agent is instructed to follow the gradient and log the contradiction. A logged contradiction reads as genuine reasoning in the trace.

**Layer 3: a deterministic compiler.** It applies the delta, clamps to the trust region, and builds the geometry:

```python
# swarm/cad/build.py
import numpy as np, cadquery as cq, trimesh

def naca4(m, p, t, n=161, te_thick=0.007):   # 0.7% c ≈ 2 mm on a 300 mm chord (FS rule T2.4.1)
    beta = np.linspace(0, np.pi, n); x = 0.5 * (1 - np.cos(beta))       # cosine spacing
    yt = 5 * t * (0.2969*np.sqrt(x) - 0.1260*x - 0.3516*x**2 + 0.2843*x**3 - 0.1015*x**4)
    yt += te_thick / 2 * x                                              # blunt TE → meshable
    yc = np.where(x < p, m/p**2*(2*p*x - x**2), m/(1-p)**2*((1-2*p) + 2*p*x - x**2)) if m > 0 else 0*x
    dyc = np.where(x < p, 2*m/p**2*(p - x), 2*m/(1-p)**2*(p - x)) if m > 0 else 0*x
    th = np.arctan(dyc)
    xu, yu = x - yt*np.sin(th), yc + yt*np.cos(th)
    xl, yl = x + yt*np.sin(th), yc - yt*np.cos(th)
    return np.vstack([np.c_[xu[::-1], yu[::-1]], np.c_[xl[1:], yl[1:]]])  # TE→upper→LE→lower→TE

def element_solid(coords, chord, aoa_deg, origin, span):
    R = np.deg2rad(-aoa_deg)
    rot = np.array([[np.cos(R), -np.sin(R)], [np.sin(R), np.cos(R)]])
    pts = (coords * chord) @ rot.T + origin
    wp = cq.Workplane("XY").polyline([tuple(p) for p in pts]).close()   # polyline > spline for robustness
    return wp.extrude(span)

def build(params: WingParams, out_dir, span=0.01):   # thin slab for 2D; full span for 3D
    main_c = 1.0 - params.flap_chord_ratio
    main = element_solid(naca4(params.main_camber, params.main_camber_pos, params.main_thickness),
                         main_c, params.alpha_deg, np.array([0, 0]), span)
    solids = {"main": main}
    if params.flap_chord_ratio > 0:
        te = np.array([main_c * np.cos(np.deg2rad(params.alpha_deg)),
                       -main_c * np.sin(np.deg2rad(params.alpha_deg))])
        origin = te + np.array([-params.slot_overlap, -params.slot_gap])
        solids["flap"] = element_solid(naca4(0.04, 0.4, 0.10), params.flap_chord_ratio,
                                       params.alpha_deg + params.flap_deflection_deg, origin, span)
    return export_and_validate(solids, out_dir)      # separate bodies → separate patches
```

Keep the elements as separate bodies; never `union` them. Separate bodies give you per-element force coefficients and named patches in snappyHexMesh.

`export_and_validate` runs these checks, and every failure becomes a string written to `pending_violation`:

- `shape.isValid()` for each solid.
- Positive volume.
- Intersection volume between elements below a small epsilon: `main.intersect(flap)`.
- Minimum gap above 0.3% chord, computed on the 2D coordinates.
- STL watertightness: `trimesh.load(stl).is_watertight`.
- Trailing-edge thickness above the mesh floor.
- Regulation compliance, when `spec.rulebook` is set (next subsection).

### Regulation compliance (Formula Student 2026)

> **Project decision (session 12): the rulebook is now the Formula SAE Rules 2027 v1.0** (`docs/FSAE_Rules_2027_V1.pdf`; `swarm/cad/regulations.py`). Key differences from the table below: rear wing height ≤ 1200 mm in the Rear Aerodynamic Zone (T.7.7.1a), 5 mm radius on forward facing horizontal edges (T.7.1.4, so NACA thickness ≥ 0.123 on a 300 mm chord), no fixed static ground clearance (V.1.4.1). Formula Student 2026 remains selectable via `DesignSpec.rulebook`.

Parameter bounds are tied to a real rulebook so every limit is traceable to a rule number. The source is the **Formula Student Rules 2026, v1.1** (Formula Student Germany; FS UK aligns closely). Formula SAE in North America has a separate rulebook with different numbers.

| Rule | Limit | Constrains |
|---|---|---|
| T8.2.1 | Devices rearward of the head-restraint plane lower than 1.1 m; forward of it lower than 500 mm | Rear wing height, position |
| T8.2.1 | Ahead of the front axle and outboard of the front tire's inboard point: lower than 250 mm | Front wing tips |
| T8.2.2 | Above 500 mm: not outboard of the rear tires' inboard points | Rear wing span (3D stage) |
| T8.2.3 | Max 250 mm behind the rear tires; max 700 mm ahead of the front tires | Overhangs |
| T8.2.4 | Limits hold with wheels straight, any suspension setup, with or without driver | Every configuration |
| T2.2.1 / T2.2.2 | Static ground clearance ≥ 30 mm; no devices touching the track | Diffuser ride height, no skirts |
| T2.4.1 | Edge radius ≥ 3 mm forward-facing, ≥ 1 mm elsewhere | Leading- and trailing-edge shape |
| T8.3.1 / T8.3.2 | 200 N over ≥ 225 cm² with ≤ 10 mm deflection; 50 N anywhere with ≤ 25 mm | Structure (outside the aero loop) |

Consequences for the parameters:

- **Trailing edge ≥ ~2 mm thick** (1 mm radius). On a 300 mm chord that is ~0.7% c, which is why `naca4` now defaults to `te_thick=0.007`.
- **Leading-edge radius ≥ 3 mm.** For NACA 4-digit sections r_LE ≈ 1.1019 t²c. On 300 mm, t = 12% gives ~4.8 mm (passes) but t = 8% gives ~2.1 mm (fails); a 100 mm flap at 10% gives ~1.1 mm (fails if its edge counts as reachable). Applied conservatively, this is a per-element thickness floor.
- **The rule box.** Every element, at every angle, must fit inside the side-view box. It depends on the car, hence `ReferenceCar` in the spec.
- **Movable devices.** FS 2026 T8 is silent on them; the FSAE 2027 draft states its aero rules do not ban DRS-type devices. Confirm with the event before relying on either (relevant to the dual-mode stretch goal).

```python
# swarm/cad/regulations.py
FS2026 = {  # Formula Student Rules 2026 v1.1
    "T8.2.1_rear_max_height_mm": 1100,
    "T8.2.1_forward_max_height_mm": 500,
    "T8.2.3_max_behind_rear_tire_mm": 250,
    "T2.4.1_min_radius_forward_mm": 3.0,
    "T2.4.1_min_radius_other_mm": 1.0,
}

def check_regulations(elements: dict[str, np.ndarray], params, car: ReferenceCar) -> list[str]:
    """elements: outlines placed in the car frame (mm). Returns violations, each naming its rule."""
    pts = np.vstack(list(elements.values()))
    v = []
    if pts[:, 1].max() >= FS2026["T8.2.1_rear_max_height_mm"]:
        v.append("T8.2.1: rear wing must be lower than 1100 mm")
    if pts[:, 0].max() > car.rear_tire_rear_x + FS2026["T8.2.3_max_behind_rear_tire_mm"]:
        v.append("T8.2.3: wing extends more than 250 mm behind the rear tires")
    fwd = pts[pts[:, 0] < car.head_restraint_x]
    if len(fwd) and fwd[:, 1].max() >= FS2026["T8.2.1_forward_max_height_mm"]:
        v.append("T8.2.1: parts forward of the head-restraint plane must be below 500 mm")
    r_le = 1.1019 * params.main_thickness**2 * car.chord_mm * (1 - params.flap_chord_ratio)
    if r_le < FS2026["T2.4.1_min_radius_forward_mm"]:
        v.append(f"T2.4.1: main-plane LE radius {r_le:.1f} mm < 3 mm; increase thickness")
    return v   # appended to pending_violation, returned to the CAD agent verbatim
```

Formula Student cars run slower than the 50 m/s reference case, so recompute `reynolds` from your target track speeds (for example, 20 m/s on 0.3 m gives Re ≈ 4×10⁵), and re-derive the validator bands at that Re.

**Escape hatch (optional, off by default):** a `generate_custom_feature(code: str)` tool that executes LLM-written CadQuery in a subprocess sandbox with no network, a timeout, and an import allowlist. It must return a solid that passes the same validators. Include it as a clearly labeled experimental mode, and measure its failure rate against the parametric mode. That comparison is a compelling ablation.

### CFD agent tools and secure execution

The LLM never produces a shell string. It fills a typed `SolverOverrides` schema. Templates render the dictionaries, and a fixed allowlist of argv sequences runs inside a locked-down container.

```python
class SolverOverrides(BaseModel):
    relax_U: float = Field(0.7, ge=0.2, le=0.9)
    relax_p: float = Field(0.3, ge=0.1, le=0.5)
    relax_turb: float = Field(0.7, ge=0.2, le=0.9)
    div_U: Literal["bounded Gauss linearUpwind grad(U)", "bounded Gauss upwind"] = \
           "bounded Gauss linearUpwind grad(U)"
    surface_level: tuple[int, int] = (5, 6)
    n_layers: int = Field(10, ge=0, le=20)
    first_layer_thickness: float = Field(2e-5, ge=5e-6, le=1e-3)
    max_iter: int = Field(3000, ge=200, le=10000)
    potential_init: bool = False
```

| Tool | Behavior |
|---|---|
| `setup_case(cid, fidelity, overrides)` | Copies `templates/<fidelity>/` and renders Jinja2 for `blockMeshDict`, `snappyHexMeshDict`, `controlDict` (with the `forceCoeffs` function object, `liftDir`/`dragDir` rotated for α, `lRef`/`Aref` set), `fvSchemes`, `fvSolution`, and `0/{U,p,k,omega,nut}` with kOmegaSST inlet values from turbulence intensity and length scale. Copies the STLs into `constant/triSurface/`. |
| `run_mesh(case)` | Runs `blockMesh → surfaceFeatureExtract → snappyHexMesh -overwrite → extrudeMesh (2D) → checkMesh`, then parses cell count, max non-orthogonality, max skewness, and "Mesh OK". |
| `run_solver(case, max_iter)` | Streams the `simpleFoam` log through the divergence monitor. |
| `parse_forces(case)` | Reads the forceCoeffs output under `postProcessing/` (file name differs between OpenFOAM versions, e.g. `coefficient.dat` or `forceCoeffs.dat`: glob, and confirm against your pinned version), then computes window means and relative standard deviations. |
| `apply_recovery(case, level)` | Applies the recovery ladder (Section 3). |
| `render_fields(case)` | Uses PyVista or `foamToVTK` to produce standardized PNGs with fixed colormaps and axes. |

The executor:

```python
# swarm/cfd/exec.py
import subprocess, shlex, os, signal, uuid

ALLOWED = {"blockMesh", "surfaceFeatureExtract", "snappyHexMesh", "extrudeMesh",
           "checkMesh", "potentialFoam", "simpleFoam", "foamToVTK", "postProcess"}
IMAGE = "opencfd/openfoam-default:2406"   # UNVERIFIED tag/path: confirm both against the image you pull
FOAM_RC = "/usr/lib/openfoam/openfoam2406/etc/bashrc"

def foam(case_dir: str, app: str, args: tuple[str, ...] = (), timeout=3600):
    if app not in ALLOWED:
        raise PermissionError(app)
    name = f"foam-{uuid.uuid4().hex[:8]}"
    inner = f"source {FOAM_RC} && {shlex.quote(app)} " + " ".join(map(shlex.quote, args)) + " -case /case"
    cmd = ["docker", "run", "--rm", "--name", name,
           "--network=none", "--cpus=4", "--memory=8g", "--pids-limit=256",
           "--security-opt=no-new-privileges", "--cap-drop=ALL",
           "--user", f"{os.getuid()}:{os.getgid()}",
           "-v", f"{os.path.abspath(case_dir)}:/case:rw",
           IMAGE, "bash", "-c", inner]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1), name
```

Everything the model can influence is a bounded float or an enum. A prompt injection or a hallucinated `rm -rf` has no path to a shell.

### Live divergence monitor

Kill runs early instead of waiting for a NaN at iteration 3000.

```python
import re, collections, time, subprocess
RES = re.compile(r"Solving for (\w+), Initial residual = ([\deE.+-]+)")
IT = re.compile(r"^Time = (\d+)")
FATAL = re.compile(r"Floating point exception|sigFpe|nan\b|-nan|Foam::error", re.I)
BOUNDING = re.compile(r"bounding (\w+), min: ([\deE.+-]+)")

def monitor(proc, name, log_path, window=100):
    it, hist, bounding = 0, collections.defaultdict(collections.deque), collections.Counter()
    with open(log_path, "w") as log:
        for line in proc.stdout:
            log.write(line)
            if m := IT.match(line): it = int(m[1])
            if FATAL.search(line):
                return _kill(name, f"FPE@it{it}")
            if m := RES.search(line):
                f, r = m[1], float(m[2]); h = hist[f]; h.append(r)
                if len(h) > window: h.popleft()
                if it > 50 and r > 1.0:
                    return _kill(name, f"residual_blowup@it{it}:{f}")
                if len(h) == window and h[-1] > 1e3 * min(h):
                    return _kill(name, f"residual_growth@it{it}:{f}")
            if m := BOUNDING.search(line):
                bounding[m[1]] += 1
                if bounding[m[1]] > 200:
                    return _kill(name, f"persistent_bounding:{m[1]}")
    return None   # finished; convergence is judged by numeric_validate

def _kill(name, sig):
    subprocess.run(["docker", "kill", name], capture_output=True)
    return sig
```

**Convergence criteria**, all of which must hold:

- Initial residuals dropped at least 4 orders for `p` and at least 5 for `U`.
- The relative standard deviation of Cl and Cd over the last 300 iterations is below 0.5%.

These thresholds are project conventions (common practice, not a standard). Confirm them in the mesh-independence study.
- `checkMesh` reports OK.

If residuals plateau while the coefficients oscillate periodically, classify the run as **UNSTEADY**, not diverged. Steady RANS oscillating on a high-lift wing usually means large-scale separation. That is a *design* signal to route to CAD, not a numerics problem to solve with more relaxation. Encoding that distinction is the kind of detail CFD reviewers look for.

---

## 3. The Self-Correction & Reasoning Loop

### Deterministic numeric validators run first

The vision model is a second opinion, never the primary judge.

| Check | Rule (2D, Re ~1e6) | Catches |
|---|---|---|
| Convergence | See criteria above | Unconverged "results" |
| Drag floor | Cd ≥ ~0.005 (flat-plate friction: 0.0029 all-laminar, 0.0097 all-turbulent, two sides; NACA 4412 min Cd ≈ 0.006 at Re 1e6 [S1]) | Mesh leaks, wrong reference values |
| Lift ceiling | \|Cl\| ≤ ~2.2 single element, ≤ ~4 two-element (loose margins above NACA 4412 Cl,max ≈ 1.67 [S1] and NASA two-element 2.82–3.32 [S6]) | Non-physical lift, broken BCs |
| L/D sanity | L/D ≤ ~200 (NACA 4412 max ≈ 130 at Re 1e6 [S1]) | Integration errors |
| Sign | Cl sign matches the geometry orientation | Flipped normals or `liftDir` |
| Mesh | maxNonOrtho < 70, skewness < 4, "Mesh OK" (checkMesh defaults [S7]) | Bad cells that corrupt results |
| y+ | Mean y+ ~1 for low-Re SST; if 30–300, wall functions must be set [S8] | Inconsistent wall treatment |
| Fidelity gap | \|ΔCl\| between tiers < 0.1 (project convention; calibrate on validation cases) | Model-form error (e.g., XFoil optimism near stall) |
| Surrogate confidence | NeuralFoil `analysis_confidence` above threshold | Out-of-distribution geometry |

The thresholds are engineering bands to tune against your validation cases, not universal constants. Say so in the README.

### Multimodal critique

**Render images deterministically.** Use fixed axes, fixed colormap ranges, and the candidate overlaid against the previous best. Annotate each image with its key numbers as text. A vision model reasons much better when every image has the same frame and the numbers are visible.

Send four images per evaluation:

1. **Cp(x/c) overlay.** Separation shows up as a pressure plateau before the trailing edge. A leading-edge spike shows as a sharp suction peak. A slot problem shows as a flap Cp that doesn't recover.
2. **Log-scale residual history.** This separates clean convergence from stalling, oscillation, and blow-up.
3. **Pressure contour zoomed on the trailing edge and slot.** This catches pressure discontinuities, checkerboarding, and flow *inside* the body (a mesh leak through a non-watertight STL).
4. **Streamlines.** These show recirculation bubbles and wake structure.

The Critic's output schema forces grounding:

```python
class Finding(BaseModel):
    observation: str                 # "Cp plateau at -0.9 on flap upper surface"
    location: str                    # "flap, x/c 0.82–1.0"
    image: Literal["cp", "residuals", "contour", "streamlines"]
    consistent_with_numeric: bool    # must reference a validator value
    severity: Literal["info", "suspect", "fatal"]
```

Enforce the asymmetry in code, not only in the prompt:

```python
def merge_verdict(numeric: NumericReport, vision: Verdict) -> Verdict:
    if not numeric.ok:
        return Verdict(status=numeric.failure_class, ...)       # vision cannot rescue
    if any(f.severity == "fatal" for f in vision.findings):
        return vision.model_copy(update={"status": "NON_PHYSICAL"})  # vision can veto
    return vision
```

**Evaluate the Critic itself with a failure zoo.** Deliberately generate around 30 broken cases:

- Leaky STL
- Flipped normals
- Wrong `Aref`
- Diverged run
- Massively separated but converged
- Too-coarse mesh with a plausible-looking Cp

Label them, and report the Critic's precision and recall with and without images. Evaluating your evaluator separates an AI engineering portfolio from a demo.

### Scenario A: hallucinated or non-physical design

1. **Schema layer.** The CAD agent proposes `slot_gap = 0.08`. Pydantic raises. The tool wrapper catches the exception and returns a `ToolError(kind="bounds", msg="slot_gap 0.08 > max 0.03", hint=...)` to the agent as a tool result. The graph never sees an exception.
2. **Trust-region layer.** A change larger than `trust_radius × range` is rejected with the allowed interval.
3. **Duplicate layer.** A repeated `cid` returns the cached result plus "propose something different."
4. **Geometry layer.** An OCC build failure, element intersection, gap below the minimum, or non-watertight STL writes `pending_violation`. The router sends the flow back to `cad_propose` with the violation verbatim, and `retries["cad"] += 1`.
5. **Deterministic fallback.** After 3 failed repairs, project the parameters onto the feasible set, or revert to the best-known design plus a small random perturbation inside the bounds. Log `{"event": "cad_fallback"}` and continue.
6. **Physics layer.** The geometry is valid but the Critic returns NON_PHYSICAL, for example Cd = 0.002. The record is appended with `quarantined=True`, so it can never become "best." If the evidence points to numerics (mesh leak, reference values), route to CFD recovery. If it points to the design, route to CAD with the diagnosis.
7. **Narrative layer.** The final report is generated only from non-quarantined ledger rows. Agent prose cannot introduce numbers.

### Scenario B: CFD divergence

1. **Detect and kill.** The monitor returns a signature such as `FPE@it37` or `persistent_bounding:omega`. `CFDResult(status="diverged", failure_signature=...)`.
2. **Classify.**

   | Signature | Likely cause | Response |
   |---|---|---|
   | Failure before iteration 50 | Mesh or boundary conditions | Re-mesh |
   | Failure later in the run | Relaxation or schemes | Numerics adjustments |
   | Persistent bounding of k or ω | Turbulence initialization or near-wall mesh | Re-initialize or adjust layers |

3. **Recovery ladder.** The CFD agent chooses a level given the evidence. Code enforces that levels are never repeated and that the ladder is bounded.

   | Level | Action |
   |---|---|
   | L1 | Lower relaxation: U 0.7→0.5, p 0.3→0.2, turbulence 0.7→0.5 |
   | L2 | First-order `upwind` for 300 iterations, then restart with `linearUpwind` from that field |
   | L3 | `potentialFoam` initialization and conservative inlet turbulence values |
   | L4 | Re-mesh: fewer or thicker layers, lower `maxNonOrtho`, more smoothing |
   | L5 | Drop fidelity: evaluate at XFoil, and mark "unsimulatable at of2d" |

4. **Escalate.** When the ladder is exhausted, route to the Chief with the full failure record. The Chief either rejects the design, since geometry that won't converge often has massive separation, or accepts the lower-fidelity result with an uncertainty flag.
5. **Crash-proof boundary.** Every node is wrapped, so the graph degrades instead of dying:

```python
def node_boundary(name):
    def deco(fn):
        def wrapped(state):
            try:
                return fn(state)
            except Exception as e:                       # tool/infra failure, not LLM output
                return {"events": [{"node": name, "error": repr(e)[:500], "gen": state["generation"]}],
                        "pending_violation": f"{name} failed: {e!s}"[:500]}
        return wrapped
    return deco

def route_after_critic(s: SwarmState) -> str:
    v, spec = s["verdict"], s["spec"]
    if len(s["ledger"]) >= spec.max_evals:
        return "report"
    if v.status == "PASS" and abs(s["result"].cl - spec.target_cl) <= spec.cl_tol \
            and s["result"].cd <= spec.cd_max:
        return "report"
    return {"NON_PHYSICAL": "cad_propose", "NUMERICAL_FAILURE": "cfd_recover",
            "UNSTEADY": "cad_propose", "TARGET_MISS": "chief_plan", "PASS": "chief_plan"}[v.status]

builder.add_conditional_edges("critic", route_after_critic,
    ["report", "cad_propose", "cfd_recover", "chief_plan"])
```

Attach a LangGraph `RetryPolicy` to the infrastructure nodes (`cfd_mesh`, `cfd_solve`) for transient Docker failures. Keep reasoning retries in your own counters so they appear in the trace.

### Hybrid optimization: the architectural decision that matters most

Pure LLM-in-the-loop optimization is sample-inefficient. Reviewers will ask why you didn't just run Bayesian optimization. The answer is that you do both.

When the Chief sets `mode="inner_optimizer"`:

1. An Optuna run (TPE) or CMA-ES (`cma`) runs K evaluations on the cheap fidelity tier.
2. The search is restricted to the Chief's `focus_params` and `trust_radius`.
3. It is warm-started from the ledger.

The LLM layer supplies what numerical optimizers lack:

- Choosing *which subspace* to search.
- Diagnosing *why* designs fail.
- Deciding when to promote fidelity.
- Recovering from infrastructure failures.

Then run the ablation: **BO only vs. LLM only vs. hybrid**, measured by evaluations to target, wall-clock time, token cost, and failure-recovery rate.

---

## 4. Lightweight POC Architecture

### Three fidelity tiers on one laptop

| Tier | Tool | Cost per evaluation (roughly) | Role |
|---|---|---|---|
| T0 | **NeuralFoil** (via `aerosandbox`) | Milliseconds | Sensitivities, inner-loop optimizer, screening |
| T1 | **XFoil** (viscous panel method with an e^N transition model) | ~0.1–2 s | Confirmation, and a real source of convergence failures |
| T2 | **2D OpenFOAM** (`simpleFoam`, kOmegaSST, one cell thick, ~100–200k cells) | Minutes on 4 cores | Two-element wings, ground effect, the full mesh→solve→recover pipeline |

T0 and T1 are enough to build and debug the entire agent graph in a weekend. Only top candidates reach T2, and the same graph runs 3D later just by changing templates.

XFoil's convergence failures are a feature for this project. Near stall and at high camber it frequently fails to converge. That gives your recovery loop a realistic, fast, free failure source to train against before OpenFOAM is involved.

### XFoil wrapper with its own recovery ladder

```python
# swarm/solvers/xfoil.py
import subprocess, tempfile, pathlib, numpy as np

def _script(coords, re, alphas, n_iter, npanel, polar):
    s = ["PLOP", "G", "", f"LOAD {coords}", "PPAR", f"N {npanel}", "", "",
         "OPER", f"VISC {re:.0f}", f"ITER {n_iter}", "PACC", str(polar), ""]
    s += [f"ALFA {a:.3f}" for a in alphas]
    return "\n".join(s + ["PACC", "", "QUIT", ""])

def run_xfoil(coords_path, re, alpha, level=0, timeout=20):
    """level 0: direct | 1: more iterations | 2: alpha continuation from 0 | 3: more panels"""
    n_iter, npanel = (100, 160) if level == 0 else (300, 160) if level == 1 else (300, 240)
    alphas = [alpha] if level < 2 else list(np.arange(0.0, alpha, 0.5 * np.sign(alpha) or 0.5)) + [alpha]
    with tempfile.TemporaryDirectory() as td:
        polar = pathlib.Path(td) / "polar.txt"
        try:
            subprocess.run(["xfoil"], input=_script(coords_path, re, alphas, n_iter, npanel, polar),
                           text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "level": level}
        rows = [l.split() for l in polar.read_text().splitlines()[12:] if l.strip()] if polar.exists() else []
        hit = [r for r in rows if abs(float(r[0]) - alpha) < 1e-3]
        if not hit:
            return {"status": "not_converged", "level": level}
        a, cl, cd, cdp, cm, *_ = map(float, hit[0])
        return {"status": "converged", "cl": cl, "cd": cd, "cm": cm, "level": level}
```

Alpha continuation (level 2) is the XFoil analogue of initializing OpenFOAM from a converged solution, so the agent learns the same recovery pattern at both fidelities.

The polar header offset (line 12) is typical but depends on the XFoil build. Parse defensively.

**Downforce convention:** in 2D freestream with no ground, simulate the upright airfoil and negate Cl. Add the ground plane (a moving wall) only at T2.

### NeuralFoil tier

```python
import aerosandbox as asb, neuralfoil as nf
af = asb.Airfoil(coordinates=coords)          # from your naca4()/CST generator
r = nf.get_aero_from_airfoil(airfoil=af, alpha=alpha, Re=re, model_size="large")
cl, cd, conf = float(r["CL"]), float(r["CD"]), float(r["analysis_confidence"])
```

Check the NeuralFoil README for the current signature. Gate on `analysis_confidence`: low confidence means the geometry is out of distribution, so escalate to XFoil.

### Build path

1. **v0: NACA 4-digit, single element, T0 + T1.** Target: |Cl| = 1.5 ± 0.03, Cd ≤ 0.018, Re = 8.3e5. The parameters are interpretable ("camber," "camber position"), which makes the agents' reasoning legible.
2. **v1: CST/Kulfan parameterization** (`asb.KulfanAirfoil`), 6–8 weights per surface. It is more expressive. The agents reason over derived semantic quantities (aft loading, LE radius) while the optimizer moves the raw weights.
3. **v2: Two-element wing at T2 in OpenFOAM.** snappyHexMesh on a thin slab, then `extrudeMesh` to one cell with `empty` front and back patches. `gmsh` with boundary-layer fields plus `gmshToFoam` is a solid alternative for 2D if snappy's layers fight you.
4. **v3: Diffuser.** XFoil can't do this; it needs T2 with a moving-ground boundary and ride height as a parameter. The physics (ground-effect venturi, stall at low ride height) is a great story for automotive reviewers.
5. **v4: 3D.** A wing with endplates needs meshes that are orders of magnitude larger, and tip vortices and induced drag become first-order effects. Run on cloud spot instances, not a laptop. Scope it honestly as future work unless you have the compute.
6. **Stretch goal: F1 2026-inspired dual-mode wing.** F1's 2026 rear wing has three elements, two of which rotate between Z-mode (maximum downforce, corners) and X-mode (low drag, straights). Borrow the idea: one shared set of element shapes, gap and overlap, with two angle settings. Z-mode must hit the downforce target under its drag cap; X-mode minimizes drag while staying attached and converged. Label it "inspired by", not F1-legal.

   ```python
   class DualModeParams(BaseModel, frozen=True):
       shape: WingParams                          # profiles, gap, overlap: shared
       z_flap_deg: float = Field(ge=20, le=45)    # cornering setting
       x_flap_deg: float = Field(ge=0, le=15)     # straight-line setting

   objectives = (abs(res_z.cl - spec.target_cl), res_x.cd)   # a vector, not one number
   ```

   - **Optimizer:** multi-objective (Optuna's NSGA-II sampler) returning a Pareto front.
   - **Chief:** picks the point on the front, e.g. "5% less cornering downforce for 20% less straight-line drag".
   - **Critic:** both modes must be converged, attached, and inside the rule box at both angles.
   - **Hysteresis check:** simulate each mode from a fresh start and continuing from the other mode's solution; different answers mean the switch is unreliable (a flap that won't reattach).
   - **Show:** the Pareto front, a morph animation between modes with each mode's Cp plot, and the hysteresis result.

Be explicit in the README that 2D results omit endplate effects, tip vortices, and induced drag. Stating limits reads as competence to automotive engineers.

---

## 5. Portfolio & Repo Showcasing

### Hero assets, in priority order

1. **Generational morph GIF.** Profile shapes from generation 0 to final, colored by objective, with Cl and Cd ticking in a corner. Put it at the top of the README; it communicates the whole project in 3 seconds.
2. **Optimization trajectory plot.** Cd vs. Cl scatter of every evaluation:
   - Color by generation.
   - Marker by fidelity tier.
   - Quarantined runs as red ×.
   - A target box, and the path of best-so-far.
3. **Ablation table.** This is the most important asset for AI companies. It needs ≥5 seeds per method and reports mean ± std.

   | Method | Evals to target | Wall clock | Tokens / $ | Success rate |
   |---|---|---|---|---|
   | Random | | | | |
   | Optuna TPE | | | | |
   | LLM only | | | | |
   | **Hybrid (swarm)** | | | | |

4. **Annotated thought-trace excerpt.** One generation rendered as a readable timeline: Chief hypothesis → CAD delta with mechanism → CFD result → Critic verdict with image findings. Also report the **sign-prediction accuracy** of the CAD agent's expected ΔCl and ΔCd.
5. **Failure-recovery reel.** A recorded run where you inject a divergence (set `relax_p` to 0.9 and an aggressive scheme) and a leaky STL. Show the monitor killing the run, the ladder climbing, and convergence. Report the recovery success rate over the failure zoo.
6. **Critic evaluation.** Precision and recall on the labeled failure zoo, with and without vision.
7. **Cp overlays across generations**, with the Critic's diagnosis annotated on the plot ("TE separation, x/c 0.82–1.0 → slot opened → recovered").

### Visualization

There are three layers, each for a different audience.

**1. Engineering plots, generated for every evaluation** (matplotlib, fixed axes and colours so every image is comparable). These are what the Critic reads and what CFD reviewers check:

- Cp(x/c) overlaid on the previous best.
- Log-scale residual history.
- Side-view profile with the Formula Student rule box drawn around it.
- For OpenFOAM runs: surface pressure, streamlines through the slot, and a velocity slice showing the wake, rendered with PyVista (or ParaView for publication-quality images) from fixed camera positions.

**2. A live run dashboard** (Streamlit is quickest) that tails `runs/<id>/ledger.jsonl` and `events.jsonl`:

- The Cl vs Cd scatter filling in, with the target box.
- The current design's profile and Cp plot.
- An agent timeline per round: Chief hypothesis → CAD change and mechanism → result → Critic verdict.
- Failures and recoveries as they happen (divergence detected, ladder level, retry outcome).
- Raw traces can be mirrored to LangSmith or Langfuse; the timeline is the readable version.

**3. The wing evolution viewer: before, middle, after.** The single most communicative asset. It shows three thumbnails (starting design, the most instructive failure, final design) above a large view with a slider that morphs the section between rounds. The starting shape stays as a dashed ghost outline, separated flow is shaded where it occurs, and Cl and Cd readouts turn green when each is inside the target.

- **The middle frame is chosen automatically:** the non-quarantined round with the largest diagnosis signal, such as the biggest drag jump or the first `TE_SEPARATION_*` verdict. That is the round that tells the story.
- **Separation shading uses solver data, not guesswork:** XFoil's skin-friction output (Cf < 0 marks reversed flow) or, for OpenFOAM, the wall-shear direction on the suction side. Shade from the first separated x/c to the trailing edge, into the wake.
- **Morphing interpolates parameters, not coordinates.** Blend two `WingParams` and rebuild the outline with `naca4`, so every in-between frame is a valid airfoil. Label interpolated frames as such; only the recorded frames carry real Cl and Cd.
- **Three outputs from one module:** a PNG strip (before, middle, after) for the README, a GIF of the full morph as the hero asset, and a self-contained HTML viewer (plain JavaScript, same NACA formula) with the slider and thumbnails for the dashboard and portfolio site.
- **Dual-mode stretch goal:** the same viewer with the slider driving the flap angle between Z-mode and X-mode instead of rounds.

```python
# swarm/viz/evolution.py
import numpy as np, matplotlib.pyplot as plt, imageio.v3 as iio
from swarm.cad.build import naca4

def placed(p, inverted=True):
    xy = naca4(p.main_camber, p.main_camber_pos, p.main_thickness)
    if inverted: xy[:, 1] *= -1                            # race-car orientation
    a = np.deg2rad(p.alpha_deg)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    return xy @ R.T                                        # trailing edge rotates up

def pick_frames(ledger):
    ok = [r for r in ledger if not r.quarantined and r.result.cl is not None]
    first, final = ok[0], min(ok, key=objective)           # objective: distance to target
    diag = [r for r in ok if r.verdict and r.verdict.diagnosis.symptom.startswith("TE_SEPARATION")]
    middle = diag[0] if diag else max(ok, key=lambda r: r.result.cd)
    return first, middle, final

def blend(pa, pb, f):
    return type(pa)(**{k: (1 - f) * getattr(pa, k) + f * getattr(pb, k)
                       for k in pa.model_fields})

def frame(p, ghost, sep_xc=None, label="", target_box=None):
    fig, ax = plt.subplots(figsize=(8, 3), dpi=120)
    g = placed(ghost); ax.plot(*g.T, "--", color="0.6", lw=1)          # starting shape
    w = placed(p);     ax.fill(*w.T, color="#5DCAA5", ec="#0F6E56")
    if sep_xc is not None:                                             # from Cf < 0
        shade_separation(ax, p, sep_xc)
    ax.set(xlim=(-0.1, 1.5), ylim=(-0.35, 0.4), aspect="equal"); ax.axis("off")
    ax.text(0, 0.35, label, fontsize=10)
    fig.canvas.draw(); img = np.asarray(fig.canvas.buffer_rgba()); plt.close(fig)
    return img

def morph_gif(records, path, steps=20):
    frames = []
    for a, b in zip(records, records[1:]):
        for f in np.linspace(0, 1, steps, endpoint=False):
            frames.append(frame(blend(a.params, b.params, f), records[0].params,
                                label=f"round {a.generation} → {b.generation} (interpolated)"))
    last = records[-1]
    frames += [frame(last.params, records[0].params,
                     label=f"final  Cl {abs(last.result.cl):.2f}  Cd {last.result.cd:.3f}")] * steps
    iio.imwrite(path, frames, duration=60, loop=0)
```

The HTML viewer is generated from the same ledger: dump the three chosen `WingParams` (plus every recorded round for the slider) as JSON into a template that recomputes the NACA outline in JavaScript. It needs no server, so it can be linked straight from the README.

### What automotive and CFD reviewers check first

- **Validation.** Compare your 2D OpenFOAM and XFoil setups against published experimental data for a standard airfoil (e.g., NACA 4412) before trusting optimizer results. Show the Cl–α and drag polar comparison.
- **Mesh independence.** Run three mesh levels with Richardson extrapolation or a Grid Convergence Index on the final design.
- **y+ distribution plot** and a justified turbulence model and wall treatment.
- **An explicit limitations section** covering 2D vs. 3D, RANS near stall, and transition modeling.

### Repo structure

```
aero-swarm/
├── README.md                 # GIF, ablation table, 90-second architecture summary, limitations
├── docker-compose.yml        # agent runtime + pinned OpenFOAM image
├── Makefile                  # `make demo` → full T0/T1 run in <10 min on a laptop
├── swarm/
│   ├── state.py  graph.py  briefs.py   # state schema, topology, per-role context builders
│   ├── agents/   chief.py cad.py cfd.py critic.py prompts/
│   ├── cad/      params.py build.py validate.py heuristics.yaml
│   ├── solvers/  neuralfoil.py xfoil.py openfoam/{exec.py,monitor.py,recovery.py}
│   ├── critic/   numeric.py render.py vision.py
│   ├── viz/      evolution.py dashboard.py templates/wing_viewer.html
│   └── optim/    inner_loop.py         # Optuna/CMA-ES, warm-started from the ledger
├── templates/of2d/           # Jinja2 OpenFOAM case
├── evals/                    # failure zoo, critic eval, ablation runner
├── validation/               # airfoil-vs-experiment, mesh independence
└── runs/<run_id>/            # ledger.jsonl, events.jsonl, traces, per-candidate artifacts
```

Log every LLM call, with prompt, output, tokens, and latency, to `runs/<id>/traces.jsonl`. Optionally mirror it to LangSmith or Langfuse. Ship one complete example run in the repo so reviewers can browse it without installing OpenFOAM.

### Suggested build order

1. T0 + T1 graph with NACA parameters and the numeric Critic only. Add the evolution viewer here: it doubles as a debugging tool.
2. Add the XFoil recovery ladder and the failure zoo.
3. Add the vision Critic and its evaluation.
4. Add the hybrid inner optimizer and the ablations.
5. Add T2 OpenFOAM with validation and mesh independence.
6. Add the diffuser.
7. Stretch: the dual-mode wing.

Each step is a shippable milestone you can post about.

---

# Part II: A Sample Run, Explained Simply

This part is written for readers who aren't from the automotive or aerodynamics field.

## The Basics First

**What's a rear wing for?** A race car's rear wing is an airplane wing mounted upside down. An airplane wing pushes air down so the plane goes up. A race car wing does the opposite: it pushes the car *down* onto the road, which gives the tires more grip for cornering. That push is called **downforce**.

**What's the catch?** Every wing also creates **drag**, the air resistance that slows the car down. Tilt a wing more steeply and you get more downforce, but also more drag. Tilt it too far and the air stops following the wing's surface and breaks away into a messy swirl. That's called **flow separation**, or **stall**. When it happens, downforce collapses and drag shoots up.

So the whole game is **getting as much downforce as you need while paying as little drag as possible.**

**Two numbers to know:**

- **Cl (lift coefficient):** how much downforce the wing makes. It's negative for downforce, but this walkthrough just says "downforce of 1.5."
- **Cd (drag coefficient):** how much drag it makes. Lower is better.

Engineers use these "coefficients" instead of raw kilograms so they can compare wing shapes fairly regardless of car speed or wing size.

**What's a simulation?** Instead of building a wing and testing it in a wind tunnel, a computer calculates how air flows around the shape and reports Cl and Cd. The system has three simulators:

- **Instant estimate (NeuralFoil):** a trained AI model that guesses the answer in milliseconds. Fast, but approximate.
- **Quick calculator (XFoil):** a classic engineering program. It takes about a second, is fairly accurate, and sometimes fails on extreme shapes.
- **Full simulation (OpenFOAM):** this one splits the air into ~150,000 tiny cells and solves the physics in each. It's the most trustworthy and takes several minutes. It can also "blow up," with the numbers exploding into nonsense, if the settings are poor.

## The Mission

> **Design a wing with downforce of 1.5 (allowed range 1.47–1.53) and drag no higher than 0.018.**

The wing shape is described by a few dials:

- **Camber:** how curved the wing is.
- **Angle:** how steeply it's tilted.
- **Thickness.**
- **Camber position:** where along the wing the curve is strongest.

The agents' job is to find the right dial settings.

The numbers below are illustrative but realistic.

## Round 0: The Starting Point

The system starts with a gently curved, lightly tilted wing (4° angle).

- **Result:** downforce 0.7, drag 0.008.
- **Critic:** "Valid simulation, but less than half the downforce we need."

## Round 1: First Improvement

The **Chief Aerodynamicist** looks at the result and forms a hypothesis:

> "The wing isn't curved or tilted enough to push much air. Increase curvature and angle."

It also checks the **sensitivities**, a quick test showing which dials have the biggest effect right now. Angle and curvature both matter a lot.

The **CAD Agent** turns that into precise changes: curvature from 2% to 6%, angle from 4° to 8°. It builds the new shape and checks it's a valid solid.

- **Result:** downforce 1.3, drag 0.013. Big progress.

## Round 2: Overdoing It, and the First Failure

The CAD Agent reasons, "more angle worked, let's go to 13°." Two things go wrong.

**First, a rejected idea.** Before that, it had also tried to make the wing 25% thick. The system instantly rejected it, because thickness has a hard limit of 18%. The rejection reason was sent back to the agent, which fixed its proposal. This is how "hallucinated" or impossible designs get caught before they waste any compute.

**Second, the simulator fails.** The quick calculator can't produce an answer at 13°. The CFD Agent doesn't crash. It follows its recovery playbook: instead of jumping straight to 13°, it starts at 0° and steps up gradually, half a degree at a time. That's like easing a car up a steep hill instead of flooring it. This time the calculation completes.

- **Result:** downforce 1.45, drag 0.024. Downforce is close, but drag blew way past the limit.

**The Critic investigates why.** It looks at the pressure graph along the wing and spots a flat section near the back edge. That flatness is the signature of air peeling away from the surface.

> **Critic's verdict:** "Target missed. Air is separating over the last 20% of the wing. The wing is starting to stall."

## Round 3: A Smarter Fix

The Chief doesn't just back off the angle. It forms a sharper hypothesis:

> "We need the downforce, but the back of the wing is overloaded. Shift the curve forward so the back half has an easier job."

The CAD Agent looks up its heuristics for "back-edge separation." Moving the curvature forward and easing the angle to 10° are the matching remedies, and the sensitivities agree.

- **Result:** downforce 1.49, drag 0.016. Both targets met on the quick calculator.

## Round 4: The High-Fidelity Check

The system now **promotes** this design to the full simulation to confirm the cheap tools weren't fooling it.

**The first attempt diverges.** At iteration 40, the numbers explode. The live monitor spots this within seconds and kills the run, so no hours are wasted.

The CFD Agent reads the failure: it happened early, and the pressure values were the ones jumping wildly. It chooses recovery level 1, "make the solver take smaller, more cautious steps." It reruns and converges cleanly.

- **Result:** downforce 1.48, drag 0.017.

**The Critic does its final checks:**

- The calculation settled properly.
- The drag isn't impossibly low.
- There's no sign of air leaking through the shape.
- The pressure graph looks healthy.
- The full simulation agrees with the quick calculator within a small margin.

> **Verdict: PASS.** Target met. The report is generated from the recorded numbers, never from the agents' own descriptions.

## What This Run Showed

| Event | What the system did |
|---|---|
| Impossible design proposed | Rejected instantly, with the reason sent back to the agent |
| Quick calculator failed | Retried with a gentler approach, no crash |
| Design looked fine but was secretly stalling | The Critic caught it from the pressure graph |
| Full simulation blew up | Detected in seconds, killed, and rerun with safer settings |
| Final answer | Cross-checked by two different simulators before being trusted |

**In one sentence:** four specialists pass a design around a loop. The Chief decides the strategy, the CAD Agent reshapes the wing, the CFD Agent tests it, and the Critic makes sure nobody is fooling themselves. They repeat until the wing hits the target, fixing their own mistakes along the way.

That last part is what makes the project impressive. Hitting the target is the easy half. Recovering on its own from bad ideas and broken simulations is what shows real engineering judgment, to AI companies and automotive teams alike.

---

## Appendix: where every number comes from

Each number in this document falls into one of five classes. Treat anything marked **Estimate** or **Convention** as a starting point to replace with your own validation data.

| Value | Class | Basis |
|---|---|---|
| q = 1,531 Pa, Re = 8.3×10⁵, M = 0.15 | Calculated | ½ρV², Vc/ν, V/a with ρ = 1.225, ν = 1.5×10⁻⁵, a = 343, V = 50 m/s, c = 0.25 m |
| Flat-plate Cf: 0.0015 laminar, 0.0048 turbulent (one side) | Calculated | 1.328/√Re and 0.074/Re^0.2 at Re = 8.3×10⁵ |
| First cell ≈ 6 μm (2.4×10⁻⁵ c) for y+ = 1 | Calculated | Turbulent Cf → τw ≈ 7.4 Pa → uτ ≈ 2.46 m/s |
| Lift slope 2π/rad ≈ 0.110/deg | Theory | Thin-airfoil theory; real sections are slightly lower |
| C_D,i ≈ 0.20 at C_L 1.5, AR 4, e 0.9 | Calculated | C_L²/(π e AR); e = 0.9 is an assumed value |
| LE radius ≈ 1.1019 t²c | Sourced | NACA 4-digit definition [S5]; ⇒ t ≥ 9.5% for 3 mm on a 300 mm chord |
| Density change ≈ M²/2 at low Mach | Theory | Isentropic relation (1.05% at M 0.15) |
| NACA 4412 at Re 1e6: Cl,max 1.67 at 16.5°, min Cd 0.0060, max L/D 130 | Sourced (computed) | NeuralFoil polar [S1]; not wind-tunnel data |
| Two-element Cl,max 2.82 (3.32 with tabs + vortex generators) | Sourced (experiment) | NASA two-element study [S6] |
| Gap 3.1–6%, overlap 3.5–6.6%, flap 22–43° | Sourced (experiment) | Configurations tested in [S6]; not universal optima |
| Gurney flap height 1–2% chord | Sourced | Typical sizing [S9] |
| Five slot effects | Sourced | A.M.O. Smith, High-Lift Aerodynamics [S4] |
| checkMesh non-orthogonality 70°, skewness 4 | Sourced | OpenFOAM source defaults [S7] |
| y+ ≈ 1 resolved (< 4–5 acceptable); 30–300 wall functions | Sourced | CFD-Wiki near-wall treatment [S8] |
| Relaxation U 0.7, p 0.3 | Sourced | OpenFOAM `airFoil2D` simpleFoam tutorial |
| XFoil Ncrit = 9 is an "average wind tunnel" | Sourced | XFoil documentation [S3] |
| RANS (SST) drag above XFoil and experiment | Sourced (direction only) | [S2]; magnitude depends on setup, so calibrate it |
| Formula Student limits (heights, overhangs, radii, clearance) | Sourced | FS Rules 2026 v1.1 |
| F1 2026 wing layout and modes | Sourced | F1 sources below |
| Target Cl 1.5 ± 0.03, Cd ≤ 0.018 | Convention | Chosen for the demo; derive yours from a NeuralFoil/XFoil sweep (≈85% of Cl,max) |
| Validator ceilings (Cl 2.2 / 4, L/D 200, Cd floor 0.005, fidelity gap 0.1) | Convention | Loose margins around the sourced values above |
| Convergence: 4–5 orders, < 0.5% std over 300 it. | Convention | Common practice; confirm with mesh-independence study |
| Recovery-ladder relaxation steps, iteration counts, trust radius | Convention | Starting values to tune |
| ~100–200k cells for 2D OpenFOAM, run times per tier | Estimate | Measure on your machine |
| Sample-run numbers (Part II) | Illustrative | Not simulation results |
| Docker image tag and bashrc path | Unverified | Check against the image you pull |

### Sources

- [S1] [NACA 4412 polars (foil.tools, NeuralFoil)](https://foil.tools/foil/naca4412)
- [S2] [Comparison between XFoil and RANS CFD predictions (Daniel CFD)](https://www.danielcfd.com/comparison-between-xfoil-rans-cfd-aerodynamic-predictions-2d-airfoil/)
- [S3] [XFoil documentation: analysis (Ncrit)](https://v0xnihili.github.io/xfoil-docs/analysis/)
- [S4] [A.M.O. Smith, High-Lift Aerodynamics](https://charles-oneill.com/aem614/ReferenceMaterial/A+M+O+Smith+HIGH+LIFT+AERODYNAMICS.pdf)
- [S5] [NACA 4-digit (modified) thickness calculation, PDAS](https://www.pdas.com/naca456thick4mcalc.html)
- [S6] [Experimental Study of Lift-Enhancing Tabs on a Two-Element Airfoil (NASA)](https://ntrs.nasa.gov/api/citations/19980019443/downloads/19980019443.pdf)
- [S7] [OpenFOAM primitiveMeshCheck.C defaults](https://cpp.openfoam.org/v7/primitiveMeshCheck_8C_source.html)
- [S8] [Near-wall treatment for k-omega models (CFD-Wiki)](https://www.cfd-online.com/Wiki/Near-wall_treatment_for_k-omega_models)
- [S9] [Gurney flap (Wikipedia)](https://en.wikipedia.org/wiki/Gurney_flap)
- [S10] LangGraph 1.2.12 source: `DEFAULT_RECURSION_LIMIT = 10007`
- [Formula Student Rules 2026 v1.1](https://www.formulastudent.de/fileadmin/user_upload/all/2026/rules/FS-Rules_2026_v1.1.pdf)
- [Formula SAE Rules 2027 draft](https://spark.docs.iitmotorsports.org/assets/resources/rulebooks/FSAE_Rules_2027_V0_DRAFT_public_comments.pdf)
- [Red Bull Racing: Guide to the 2026 technical regulations](https://www.redbullracing.com/int-en/projects/bulls-guide-to-the-f1-2026-regulations/technical-regulations)
- [F1 Briefing: F1 rear wing rules and downforce](https://f1briefing.com/rear-wing-rules-impact-on-f1-downforce/)
