"""CAD Generative Agent: converts diagnoses into bounded parameter deltas. Output: ParamDelta."""

from __future__ import annotations

from swarm.briefs import cad_brief
from swarm.llm.client import LLMClient
from swarm.state import EvalRecord, ParamDelta, SwarmState, WingParams


def propose(llm: LLMClient, state: SwarmState, base: WingParams, base_rec: EvalRecord | None, sens: dict) -> ParamDelta:
    b = cad_brief(state, base, base_rec, sens)
    return llm.structured("cad", b.system, b.user, ParamDelta, facts=b.facts)
