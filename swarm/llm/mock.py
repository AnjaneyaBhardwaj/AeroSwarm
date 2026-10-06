"""MockClient — a deterministic, rule-based stand-in for the LLM.

FOR TESTS AND DEMOS ONLY. This is NOT an LLM. It reads the same facts the
real model receives in its brief and applies fixed rules (a damped
least-norm step on NeuralFoil sensitivities, a fixed promotion policy, the
deterministic suggested diagnosis). Runs made with it are labelled
`mock` in meta.json and traces.jsonl. Never use it as the "LLM" arm of a
comparison or ablation: `swarm.llm.client.require_real_llm` rejects it.
"""

from __future__ import annotations

import re
import time

import numpy as np

from swarm.cad.heuristics import HEURISTICS
from swarm.state import (
    Diagnosis,
    Finding,
    ParamChange,
    ParamDelta,
    StrategyMemo,
    Verdict,
    WingParams,
    quantize,
)

INNER_AFTER_STREAK = 2
MOCK_LABEL = "mock (deterministic rule-based stand-in for tests/demos; NOT an LLM)"


def _sign(x: float, eps: float = 1e-9) -> int:
    return 0 if abs(x) < eps else (1 if x > 0 else -1)


class MockClient:
    kind = "mock"
    is_mock = True
    label = MOCK_LABEL

    def __init__(self, trace, inject_faults: bool = False, inner_budget: int = 0):
        self.trace = trace
        self.inject_faults = inject_faults
        # > 0: when the run allows it, hand the focus subspace to the inner optimizer after
        # INNER_AFTER_STREAK generations without improvement (0 = never; the default mock is unchanged)
        self.inner_budget = inner_budget
        self._injected: set[str] = set()

    def structured(self, role, system, user, schema, facts=None):
        if facts is None:
            raise ValueError("MockClient needs the brief facts")
        t0 = time.perf_counter()
        extra = {"mock": True}
        if schema is StrategyMemo:
            out = self._chief(facts)
        elif schema is ParamDelta:
            out, injected = self._cad(facts)
            if injected:
                extra["injected_fault"] = injected
        elif schema is Verdict:
            out = self._critic(facts)
        else:
            raise TypeError(f"MockClient cannot produce {schema.__name__}")
        self.trace.log(
            role=role,
            client=self.kind,
            model="mock",
            schema=schema.__name__,
            system=system,
            user=user,
            output=out.model_dump(),
            usage={},
            latency_s=time.perf_counter() - t0,
            extra=extra,
        )
        return out

    # ------------------------------------------------------------- chief
    def _chief(self, f: dict) -> StrategyMemo:
        spec, free = f["spec"], f["free_params"]
        best, best_x = f["best"], f["best_xfoil"]
        tol = spec["cl_tol"]
        streak = f["no_improve_streak"]
        if best and streak >= 8:
            return StrategyMemo(
                hypothesis=f"Plateau: no improvement in {streak} generations.",
                focus_params=free[:1],
                trust_radius=0.05,
                fidelity="neuralfoil",
                mode="reasoned_step",
                declare_plateau=True,
            )
        if f["promotable"]:
            cid = f["promotable"][0]
            return StrategyMemo(
                hypothesis=f"Candidate {cid} is within 2·tol of the target at neuralfoil; "
                "confirm it at xfoil before trusting the surrogate.",
                focus_params=free[:3],
                trust_radius=0.1,
                fidelity="xfoil",
                mode="reasoned_step",
                promote_cid=cid,
            )
        fid = "neuralfoil"
        ref = best
        if best_x and abs(best_x["cl"] - spec["target_cl"]) <= 4 * tol:
            fid, ref = "xfoil", best_x
        if ref is None:
            return StrategyMemo(
                hypothesis="No data yet; screen the baseline.",
                focus_params=free[:3],
                trust_radius=0.15,
                fidelity=fid,
                mode="reasoned_step",
            )
        sens = f["sensitivities"]
        rng = {p: WingParams.bounds()[p][1] - WingParams.bounds()[p][0] for p in free}
        cd_over = ref["cd"] > spec["cd_max"]
        key = "dCd" if cd_over else "dCl"
        ranked = sorted((p for p in free if p in sens), key=lambda p: -abs(sens[p][key]) * rng[p])
        focus = ranked[:3] or free[:3]
        err = ref["cl"] - spec["target_cl"]
        inner = f.get("inner_optimizer") or {}
        last_mode = (f.get("last_strategy") or {}).get("mode")
        if (
            self.inner_budget > 0
            and inner.get("allowed")
            and streak >= INNER_AFTER_STREAK
            and last_mode != "inner_optimizer"
        ):
            return StrategyMemo(
                hypothesis=f"No improvement in {streak} generations; inner optimizer over {', '.join(focus)}.",
                focus_params=focus,
                trust_radius=0.15,
                fidelity="neuralfoil",
                mode="inner_optimizer",
                inner_budget=self.inner_budget,
            )
        radius = 0.3 if streak >= 3 else (0.08 if abs(err) <= 3 * tol else 0.15)
        if cd_over:
            hyp = (
                f"Drag limits the design: Cd={ref['cd']:.4f} > {spec['cd_max']}; "
                f"{focus[0]} has the largest drag leverage."
            )
        elif err > 0:
            hyp = (
                f"Loading is insufficient: Cl={ref['cl']:.3f} vs target {spec['target_cl']}; "
                f"{focus[0]} has the largest lift leverage."
            )
        else:
            hyp = (
                f"Overloaded: Cl={ref['cl']:.3f} beyond target {spec['target_cl']}; "
                f"unload via {focus[0]} to buy back drag margin."
            )
        return StrategyMemo(hypothesis=hyp, focus_params=focus, trust_radius=radius, fidelity=fid, mode="reasoned_step")

    # ------------------------------------------------------------- cad
    def _cad(self, f: dict) -> tuple[ParamDelta, str | None]:
        key = f"gen{f['generation']}"
        if self.inject_faults and f["generation"] == 2 and key not in self._injected:
            self._injected.add(key)
            p = f["focus_params"][0]
            lo, hi = WingParams.bounds()[p]
            ch = ParamChange(
                name=p,
                new_value=round(hi + 0.5 * (hi - lo), 4),
                mechanism=f"[INJECTED FAULT] push {p} far beyond its bound",
                expected_dCl_sign=0,
                expected_dCd_sign=0,
            )
            return ParamDelta(changes=[ch], note="[INJECTED FAULT] deliberate bounds violation"), "bounds_violation"
        spec, base, res = f["spec"], f["base"], f["base_result"]
        focus, sens, iv = f["focus_params"], f["sensitivities"], f["intervals"]
        new = dict(base)
        pv = f.get("pending_violation") or ""
        m = re.search(r"main_thickness to at least ([0-9.]+)", pv)
        if m and "main_thickness" in focus:
            new["main_thickness"] = min(iv["main_thickness"][1], float(m.group(1)) + 2e-4)
        names = [p for p in focus if p in sens]
        if res and names:
            rng = np.array([WingParams.bounds()[p][1] - WingParams.bounds()[p][0] for p in names])
            a = np.array([sens[p]["dCl"] for p in names]) * rng
            b = np.array([sens[p]["dCd"] for p in names]) * rng
            d_cl = spec["target_cl"] - res["cl"]
            rows, rhs = [a], [d_cl]
            if res["cd"] > spec["cd_max"]:
                rows.append(b * 10.0)
                rhs.append((0.95 * spec["cd_max"] - res["cd"]) * 10.0)
            x, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
            step = 0.8 * x * rng
            for p, dp in zip(names, step, strict=True):
                lo, hi = iv[p]
                new[p] = float(np.clip(base[p] + dp, lo, hi))
        changed = [p for p in focus if abs(quantize(new[p]) - base[p]) >= 1e-4]
        if not changed and focus:
            p = focus[0]
            lo, hi = iv[p]
            new[p] = hi if hi - base[p] >= base[p] - lo else lo
            new[p] = base[p] + 0.5 * (new[p] - base[p])
            changed = [p]
        changed = sorted(changed, key=lambda p: -abs(new[p] - base[p]))[:3]
        diag = (f.get("diagnosis") or {}).get("symptom", "NONE")
        heur = {p: (d, m) for p, d, m in HEURISTICS.get(diag, [])}
        notes, changes = [], []
        for p in changed:
            dv = quantize(new[p]) - base[p]
            s = sens.get(p, {"dCl": 0.0, "dCd": 0.0})
            mech = f"{'increase' if dv > 0 else 'decrease'} {p} along the sensitivity gradient"
            if p in heur:
                d, hm = heur[p]
                if d and _sign(dv) != d:
                    notes.append(
                        f"heuristic for {diag} says {p} {'+' if d > 0 else '-'}; "
                        "sensitivities disagree; following sensitivities"
                    )
                elif hm:
                    mech = hm
            want = (f.get("directions") or {}).get(p, "free")
            against = want != "free" and (want == "+") != (dv > 0)
            changes.append(
                ParamChange(
                    name=p,
                    new_value=quantize(new[p]),
                    mechanism=mech,
                    expected_dCl_sign=_sign(s["dCl"] * dv, 1e-6),
                    expected_dCd_sign=_sign(s["dCd"] * dv, 1e-7),
                    override_reason="the sensitivity step points the other way" if against else "",
                )
            )
        return ParamDelta(changes=changes, note="; ".join(notes)), None

    # ------------------------------------------------------------- critic
    def _critic(self, f: dict) -> Verdict:
        d = Diagnosis(**f["suggested_diagnosis"])
        findings = []
        for c in f["numeric"]["checks"]:
            if not c["ok"] or c["severity"] == "suspect":
                findings.append(
                    Finding(
                        observation=f"{c['name']}: {c['message']} (value {c['value']})",
                        location="global",
                        source="numeric",
                        consistent_with_numeric=True,
                        severity="suspect" if c["severity"] != "fatal" else "info",
                    )
                )
        bl = (f["result"] or {}).get("bl") or {}
        if bl.get("te_separation_xc") is not None:
            findings.append(
                Finding(
                    observation="suction-side Cf<0 persists to the trailing edge",
                    location=f"x/c {bl['te_separation_xc']:.2f}-1.00",
                    source="boundary_layer",
                    consistent_with_numeric=True,
                )
            )
        for a, b in bl.get("bubbles") or []:
            findings.append(
                Finding(
                    observation="laminar separation bubble (reattaches)",
                    location=f"x/c {a:.2f}-{b:.2f}",
                    source="boundary_layer",
                    consistent_with_numeric=True,
                )
            )
        return Verdict(status=f["numeric_status"], diagnosis=d, findings=findings, confidence=0.7)
