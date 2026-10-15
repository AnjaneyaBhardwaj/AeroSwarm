"""Live divergence monitor for simpleFoam logs (BLUEPRINT §2 "Live divergence monitor").

Fed one log line at a time by `swarm.solvers.openfoam.exec.run`; returns a failure signature to kill the run:
- `FPE@it<n>`: a floating-point exception or NaN in the log (also found after the fact by `post_mortem` when
  the solver aborted itself, as FOAM_SIGFPE makes it do);
- `solver_blowup@it<n>:<field>`: a linear solve ending with a final residual above 1e6 (seen several lines
  before the FPE);
- `residual_blowup@it<n>:<field>`: an initial residual above 1 after iteration 50;
- `residual_growth@it<n>:<field>`: the residual 1000x above its minimum over the last 100 iterations;
- `persistent_bounding:<field>`: more than 200 "bounding" messages for k or omega.
The signature's iteration lets the CFD agent classify the failure (early: mesh / BCs; late: numerics).
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

RES = re.compile(r"Solving for (\w+), Initial residual = ([-+\deE.naif]+), Final residual = ([-+\deE.naif]+)")
IT = re.compile(r"^Time = (\d+)")
# Not "Floating point exception trapping enabled": that is the startup banner.
FATAL = re.compile(r"sigFpe::sigHandler|printStack|Floating point exception \(core|\bnan\b|FOAM FATAL")
SOLVER_BLOWUP = 1e6  # a linear solve whose final residual exceeds this has already diverged
BOUNDING = re.compile(r"bounding (\w+), min: ([-+\deE.]+)")


class Monitor:
    def __init__(self, window: int = 100, blowup_after: int = 50, growth: float = 1e3, max_bounding: int = 200):
        self.window, self.blowup_after, self.growth, self.max_bounding = window, blowup_after, growth, max_bounding
        self.it = 0
        self.hist: dict[str, collections.deque] = collections.defaultdict(collections.deque)
        self.bounding: collections.Counter = collections.Counter()

    def feed(self, line: str) -> str | None:
        if m := IT.match(line):
            self.it = int(m[1])
            return None
        if FATAL.search(line):
            return f"FPE@it{self.it}"
        if m := RES.search(line):
            field = m[1]
            try:
                r, final = float(m[2]), float(m[3])
            except ValueError:
                return f"FPE@it{self.it}"
            if r != r or final != final:  # NaN
                return f"FPE@it{self.it}"
            if final > SOLVER_BLOWUP:
                return f"solver_blowup@it{self.it}:{field}"
            h = self.hist[field]
            h.append(r)
            if len(h) > self.window:
                h.popleft()
            if self.it > self.blowup_after and r > 1.0:
                return f"residual_blowup@it{self.it}:{field}"
            if len(h) == self.window and min(h) > 0 and h[-1] > self.growth * min(h):
                return f"residual_growth@it{self.it}:{field}"
            return None
        if m := BOUNDING.search(line):
            self.bounding[m[1]] += 1
            if self.bounding[m[1]] > self.max_bounding:
                return f"persistent_bounding:{m[1]}"
        return None

    def post_mortem(self, log: str | Path) -> str | None:
        """Signature for a run that ended by itself with an error (the monitor saw no fatal line in time)."""
        it = 0
        for line in Path(log).read_text().splitlines():
            if m := IT.match(line):
                it = int(m[1])
            elif FATAL.search(line):
                return f"FPE@it{it}"
        return None


def iteration_of(signature: str | None) -> int | None:
    m = re.search(r"@it(\d+)", signature or "")
    return int(m[1]) if m else None
