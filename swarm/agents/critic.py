"""Engineering Critic: the only agent allowed to declare a result valid. Output: Verdict.

The numeric report is authoritative; `merge_verdict` enforces in code that
the LLM can downgrade a result but never upgrade a failed numeric check.
"""

from __future__ import annotations

from swarm.briefs import critic_brief
from swarm.critic.numeric import NumericReport, suggest_diagnosis
from swarm.llm.client import LLMClient
from swarm.state import EvalRecord, SwarmState, Verdict


def merge_verdict(numeric: NumericReport, llm: Verdict) -> Verdict:
    if not numeric.ok:
        return llm.model_copy(update={"status": numeric.failure_class})  # LLM cannot rescue
    if any(f.severity == "fatal" for f in llm.findings):
        return llm.model_copy(update={"status": "NON_PHYSICAL"})  # LLM can veto
    # The LLM may downgrade (anything → a non-PASS status) but never upgrade to PASS.
    if llm.status != "PASS" and llm.status != numeric.status:
        return llm
    return llm.model_copy(update={"status": numeric.status})


def review(llm: LLMClient, state: SwarmState, parent_rec: EvalRecord | None) -> Verdict:
    numeric: NumericReport = state["numeric"]
    suggested = suggest_diagnosis(state["result"], state["spec"], parent_rec.result if parent_rec else None)
    b = critic_brief(state, suggested, parent_rec)
    raw = llm.structured("critic", b.system, b.user, Verdict, facts=b.facts)
    return merge_verdict(numeric, raw)
