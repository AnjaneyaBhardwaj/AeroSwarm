"""Engineering Critic: the only agent allowed to declare a result valid. Output: Verdict.

The numeric report is authoritative; `merge_verdict` enforces in code that
the LLM can downgrade a result but never upgrade a failed numeric check.
"""

from __future__ import annotations

from swarm.briefs import critic_brief
from swarm.critic.numeric import NumericReport, suggest_diagnosis
from swarm.llm.client import LLMClient
from swarm.state import EvalRecord, SwarmState, Verdict

STALL_CHECKS = ("stall_margin", "neuralfoil_screen")


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
    suggested = suggest_diagnosis(
        state["result"],
        state["spec"],
        parent_rec.result if parent_rec else None,
        stall=state.get("stall"),
        screen=state.get("screen"),
    )
    b = critic_brief(state, suggested, parent_rec)
    raw = llm.structured("critic", b.system, b.user, Verdict, facts=b.facts)
    v = merge_verdict(numeric, raw)
    # TE separation is TARGET_MISS with a separation diagnosis, whatever the LLM labelled it.
    if any(c.name == "te_separation" and not c.ok for c in numeric.checks) and not v.diagnosis.symptom.startswith(
        ("TE_SEPARATION", "EARLY_STALL")
    ):
        v = v.model_copy(update={"diagnosis": suggested})
    # A failed stall margin or NeuralFoil screen is EARLY_STALL, with the deterministic evidence.
    elif any(c.name in STALL_CHECKS and not c.ok for c in numeric.checks) and suggested.symptom == "EARLY_STALL":
        if v.diagnosis.symptom != "EARLY_STALL":
            v = v.model_copy(update={"diagnosis": suggested})
        else:  # keep the LLM's wording, add the numbers it must not lose
            extra = [e for e in suggested.evidence if e not in v.diagnosis.evidence]
            v = v.model_copy(
                update={"diagnosis": v.diagnosis.model_copy(update={"evidence": extra + v.diagnosis.evidence})}
            )
    return v
