"""Runs OpenFOAM applications: a fixed allowlist, argv only (no shell), output streamed to a log.

BLUEPRINT §2 runs OpenFOAM in a locked-down Docker container. This environment has no Docker daemon and its
network policy blocks the OpenFOAM image hosts, so the Ubuntu package (ESI OpenFOAM v1912, binaries on PATH,
`WM_PROJECT_DIR=/usr/share/openfoam`) runs natively instead. What keeps an LLM away from a shell is unchanged:
agents only fill `SolverOverrides` (bounded numbers and booleans), case files are written by code, and only the
applications in ALLOWED can be started, with argv built here.

`on_line(line) -> str | None` sees every output line; a non-None return kills the run (the divergence monitor,
`swarm.solvers.openfoam.monitor`) and becomes the failure signature.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ALLOWED = frozenset({"simpleFoam", "potentialFoam", "checkMesh"})
FOAM_DIR = os.environ.get("AEROSWARM_FOAM_DIR", "/usr/share/openfoam")


def foam_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
    env["WM_PROJECT_DIR"] = FOAM_DIR
    env.setdefault("FOAM_SIGFPE", "true")  # a floating-point exception aborts the run instead of spreading NaN
    return env


def available() -> bool:
    return shutil.which("simpleFoam") is not None and (Path(FOAM_DIR) / "etc" / "controlDict").exists()


@dataclass
class RunOutcome:
    returncode: int | None
    signature: str | None  # set when the monitor killed the run or it timed out
    log_path: str
    wall_s: float


def run(
    app: str,
    case_dir: str | Path,
    args: tuple[str, ...] = (),
    timeout: float = 3600.0,
    on_line: Callable[[str], str | None] | None = None,
    log_name: str | None = None,
) -> RunOutcome:
    if app not in ALLOWED:
        raise PermissionError(f"{app} is not an allowed OpenFOAM application")
    case = Path(case_dir).resolve()
    log = case / (log_name or f"log.{app}")
    t0 = time.perf_counter()
    signature = None
    with log.open("w") as fh:
        proc = subprocess.Popen(
            [app, "-case", str(case), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=foam_env(),
            start_new_session=True,  # its own process group, so a kill takes the whole run
        )
        try:
            for line in proc.stdout:
                fh.write(line)
                if signature is None and on_line is not None:
                    signature = on_line(line)
                    if signature:
                        _kill(proc)
                        break
                if time.perf_counter() - t0 > timeout:
                    signature = f"timeout@{timeout:.0f}s"
                    _kill(proc)
                    break
        finally:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _kill(proc)
                proc.wait()
    return RunOutcome(proc.returncode, signature, str(log), time.perf_counter() - t0)


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
