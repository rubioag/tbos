"""CE.4 — Action Selection (spec: Action Selection Principle).

v1 decision space is effectively {BET_NOW, DEFER, PASS} — WAIT_FOR_PRICE
and MONITOR_LIVE_CONDITION need CE.5's real-time monitoring loop (not
built yet), and SPLIT_EXPOSURE needs IL.4 Portfolio Construction (not
built yet). Both remain valid taxonomy values, just unreachable from this
Engine until those dependencies exist — documented, not faked.

Rules, checked in order:
1. Non-positive expected EV -> PASS.
2. Robustness below the aggressiveness threshold -> DEFER (marginal edge,
   not wrong, just not strong enough yet).
3. Behavioral Bias Checklist failed -> DEFER (needs human review before
   any capital commitment).
4. Ruin-risk check failed -> PASS (hard capital-safety gate, not a
   "wait and see" — rejected outright, never downsized automatically in v1).
5. Otherwise -> BET_NOW at the computed stake.
"""

from __future__ import annotations

from pydantic import BaseModel

from tbos.ce4_decision.bias import BiasChecklistResult
from tbos.ce4_decision.ruin_risk import RuinRiskResult
from tbos.ce4_decision.stake import StakeResult
from tbos.ce3_edge.schemas import EdgeDescription
from tbos.inf1_config.taxonomy import ActionType


class DominantReason(BaseModel):
    code: str
    justification: str


def select_action(
    edge: EdgeDescription,
    stake_result: StakeResult,
    bias_result: BiasChecklistResult,
    ruin_result: RuinRiskResult,
    *,
    aggressiveness_threshold: float,
) -> tuple[ActionType, DominantReason]:
    if edge.ev_distribution.expected <= 0:
        return ActionType.PASS, DominantReason(
            code="NON_POSITIVE_EV", justification=f"expected EV {edge.ev_distribution.expected:.4f} <= 0"
        )

    if edge.edge_robustness.score < aggressiveness_threshold:
        return ActionType.DEFER, DominantReason(
            code="MARGINAL_ROBUSTNESS",
            justification=(
                f"robustness {edge.edge_robustness.score:.2f} below aggressiveness "
                f"threshold {aggressiveness_threshold:.2f}"
            ),
        )

    if not bias_result.passed:
        triggered = [f.bias_type for f in bias_result.flags if f.triggered]
        return ActionType.DEFER, DominantReason(
            code="BEHAVIORAL_BIAS_FLAGGED", justification=f"flagged: {triggered}"
        )

    if not ruin_result.passed:
        return ActionType.PASS, DominantReason(
            code="RUIN_RISK_EXCEEDED",
            justification=f"ruin_probability {ruin_result.ruin_probability:.4f} exceeds configured maximum",
        )

    return ActionType.BET_NOW, DominantReason(
        code="POSITIVE_EV_ROBUST",
        justification=(
            f"expected EV {edge.ev_distribution.expected:.4f}, "
            f"robustness {edge.edge_robustness.score:.2f}, stake {stake_result.stake_amount:.2f}"
        ),
    )
