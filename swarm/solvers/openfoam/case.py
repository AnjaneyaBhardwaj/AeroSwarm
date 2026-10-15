"""OpenFOAM case files for the 2D section (T2, `of2d`): simpleFoam, k-omega SST, steady.

Non-dimensional: chord 1, |U| 1, nu = 1 / Re, rho = 1 (kinematic pressure). The freestream comes in at the
angle of attack (the mesh is the upright, unrotated section, as at T0/T1); lift and drag are rotated with it
(swarm.solvers.openfoam.forces). Low-Re wall treatment (first cell y+ ~ 1; k = 0 and omega from the wall
function at the wall).
The LLM never writes these files: `SolverOverrides` (bounded numbers and enums) is all it can set.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SolverOverrides(BaseModel, frozen=True):
    """What a recovery action may change (BLUEPRINT §2 "CFD agent tools"). Defaults are the L0 setup."""

    relax_U: float = Field(0.7, ge=0.2, le=0.9)
    relax_p: float = Field(0.3, ge=0.1, le=0.5)
    relax_turb: float = Field(0.7, ge=0.2, le=0.9)
    first_order: bool = False  # bounded Gauss upwind for U for the whole run; k and omega are always upwind
    first_order_iters: int = Field(0, ge=0, le=2000)  # L2: first-order U for this many iterations, then second order
    potential_init: bool = False  # potentialFoam initial field (L3)
    turbulence_intensity: float = Field(0.001, ge=1e-4, le=0.05)  # freestream Tu
    viscosity_ratio: float = Field(0.1, ge=1e-3, le=10.0)  # freestream nut / nu
    max_iter: int = Field(3000, ge=200, le=10000)


FIELDS = ("U", "p", "k", "omega", "nut")
# Forces come from the written fields (swarm.solvers.openfoam.forces), not a function object: function objects
# abort with an "sha1" IOstream error in the Debian v1912 build. Every WRITE_EVERY iterations a time directory is
# written and the last KEEP_WRITES are kept, so the coefficient history covers the last 300+ iterations.
WRITE_EVERY = 50
KEEP_WRITES = 8


def _hdr(cls: str, obj: str, loc: str) -> str:
    return (
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
        f'    class       {cls};\n    location    "{loc}";\n    object      {obj};\n}}\n\n'
    )


def freestream(alpha_deg: float) -> tuple[float, float]:
    a = math.radians(alpha_deg)
    return math.cos(a), math.sin(a)


TurbulenceModel = Literal["kOmegaSST", "kOmegaSSTLM"]


def retheta_t_freestream(tu: float) -> float:
    """Langtry-Menter correlation for the freestream transition-onset momentum-thickness Reynolds number
    (Tu as a fraction; the correlation's Tu <= 1.3% branch, pressure-gradient term zero)."""
    t = max(100.0 * tu, 0.027)  # percent; the correlation is bounded below by Tu = 0.027%
    return 1173.51 - 589.428 * t + 0.2196 / t**2


def write_case(
    case_dir: str | Path,
    alpha_deg: float,
    reynolds: float,
    span: float,
    ov: SolverOverrides,
    model: TurbulenceModel = "kOmegaSST",
) -> None:
    """`model`: kOmegaSST (fully turbulent) or kOmegaSSTLM (Langtry-Menter gamma-Re_theta transition). A physics
    choice of the case, not something a recovery action may change."""
    d = Path(case_dir)
    for sub in ("system", "constant", "0"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    ux, uy = freestream(alpha_deg)
    nu = 1.0 / reynolds
    k_inf = 1.5 * ov.turbulence_intensity**2
    omega_inf = k_inf / (nu * ov.viscosity_ratio)
    div_u = "bounded Gauss upwind" if ov.first_order else "bounded Gauss linearUpwind grad(U)"
    # k and omega: first order always. Second order bounded omega in every iteration of the NACA 0012 validation
    # (minimum about -50) with the same forces (Cl 1.0919 vs 1.0921, Cd 0.01376 vs 0.01372; docs/OPENFOAM.md).
    div_t = "bounded Gauss upwind"

    (d / "system" / "controlDict").write_text(
        _hdr("dictionary", "controlDict", "system")
        + f"""// span {span}
application simpleFoam;
startFrom latestTime;
startTime 0;
stopAt endTime;
endTime {ov.max_iter};
deltaT 1;
writeControl timeStep;
writeInterval {WRITE_EVERY};
purgeWrite {KEEP_WRITES};
writeFormat ascii;
writePrecision 8;
timeFormat general;
timePrecision 6;
runTimeModifiable false;

"""
    )
    (d / "system" / "fvSchemes").write_text(
        _hdr("dictionary", "fvSchemes", "system")
        + f"""ddtSchemes {{ default steadyState; }}
gradSchemes {{ default Gauss linear; grad(U) cellLimited Gauss linear 1;
    grad(k) cellLimited Gauss linear 1; grad(omega) cellLimited Gauss linear 1; }}
divSchemes
{{
    default none;
    div(phi,U) {div_u};
    div(phi,k) {div_t};
    div(phi,omega) {div_t};
    div(phi,ReThetat) {div_t};
    div(phi,gammaInt) {div_t};
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear corrected; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default corrected; }}
wallDist {{ method meshWave; }}
"""
    )
    (d / "system" / "fvSolution").write_text(
        _hdr("dictionary", "fvSolution", "system")
        + f"""solvers
{{
    p {{ solver PCG; preconditioner DIC; tolerance 1e-8; relTol 0.05; maxIter 2000; }}
    Phi {{ solver PCG; preconditioner DIC; tolerance 1e-8; relTol 0.01; maxIter 2000; }}
    "(U|k|omega|ReThetat|gammaInt)" {{ solver smoothSolver; smoother symGaussSeidel; tolerance 1e-9; relTol 0.1; }}
}}
SIMPLE
{{
    nNonOrthogonalCorrectors 0;
    consistent no;
    residualControl {{ p 1e-6; U 1e-7; "(k|omega|ReThetat|gammaInt)" 1e-7; }}
}}
potentialFlow {{ nNonOrthogonalCorrectors 3; }}
relaxationFactors
{{
    fields {{ p {ov.relax_p}; }}
    equations {{ U {ov.relax_U}; "(k|omega|ReThetat|gammaInt)" {ov.relax_turb}; }}
}}
"""
    )
    (d / "constant" / "transportProperties").write_text(
        _hdr("dictionary", "transportProperties", "constant") + f"transportModel Newtonian;\nnu {nu:.10g};\n"
    )
    (d / "constant" / "turbulenceProperties").write_text(
        _hdr("dictionary", "turbulenceProperties", "constant")
        + f"simulationType RAS;\nRAS {{ RASModel {model}; turbulence on; printCoeffs off; }}\n"
    )
    far_u = f"type freestreamVelocity; freestreamValue uniform ({ux:.10f} {uy:.10f} 0);"
    fields = {
        "U": ("volVectorField", "[0 1 -1 0 0 0 0]", f"({ux:.10f} {uy:.10f} 0)", "type noSlip;", far_u),
        "p": ("volScalarField", "[0 2 -2 0 0 0 0]", "0", "type zeroGradient;",
              "type freestreamPressure; freestreamValue uniform 0;"),
        "k": ("volScalarField", "[0 2 -2 0 0 0 0]", f"{k_inf:.10g}", "type fixedValue; value uniform 1e-12;",
              f"type inletOutlet; inletValue uniform {k_inf:.10g}; value uniform {k_inf:.10g};"),
        "omega": ("volScalarField", "[0 0 -1 0 0 0 0]", f"{omega_inf:.10g}",
                  f"type omegaWallFunction; value uniform {omega_inf:.10g};",
                  f"type inletOutlet; inletValue uniform {omega_inf:.10g}; value uniform {omega_inf:.10g};"),
        "nut": ("volScalarField", "[0 2 -1 0 0 0 0]", "0", "type nutLowReWallFunction; value uniform 0;",
                "type calculated; value uniform 0;"),
    }  # fmt: skip
    if model == "kOmegaSSTLM":
        rt = retheta_t_freestream(ov.turbulence_intensity)
        dimless = "[0 0 0 0 0 0 0]"
        fields["ReThetat"] = (
            "volScalarField",
            dimless,
            f"{rt:.6g}",
            "type zeroGradient;",
            f"type inletOutlet; inletValue uniform {rt:.6g}; value uniform {rt:.6g};",
        )
        fields["gammaInt"] = ("volScalarField", dimless, "1", "type zeroGradient;",
                              "type inletOutlet; inletValue uniform 1; value uniform 1;")  # fmt: skip
    for name, (cls, dim, internal, wall, far) in fields.items():
        (d / "0" / name).write_text(
            _hdr(cls, name, "0") + f"dimensions {dim};\ninternalField uniform {internal};\nboundaryField\n{{\n"
            f"    airfoil {{ {wall} }}\n    farfield {{ {far} }}\n    frontAndBack {{ type empty; }}\n}}\n"
        )
