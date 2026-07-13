"""CE.4 — Behavioral Bias Checklist. Pre-commit gate, runs before any
capital is ever proposed for placement (spec: gate previo a compromiso de
capital). Two v1 checks, both computable from data already on hand;
richer checks (loss-chasing, recency) need historical decision context
(INF.3) not wired into this pure function yet.
"""

from __future__ import annotations

from pydantic import BaseModel

OVERCONFIDENCE_FRACTION_THRESHOLD = 0.15  # v1 placeholder: no single bet should exceed 15% of bankroll
FRAGILE_ROBUSTNESS_THRESHOLD = 0.2


class BiasFlag(BaseModel):
    bias_type: str
    triggered: bool
    evidence: str


class BiasChecklistResult(BaseModel):
    passed: bool
    flags: list[BiasFlag]


def run_bias_checklist(*, adjusted_stake_fraction: float, robustness_score: float) -> BiasChecklistResult:
    overconfidence = adjusted_stake_fraction > OVERCONFIDENCE_FRACTION_THRESHOLD
    fragile_pursuit = robustness_score < FRAGILE_ROBUSTNESS_THRESHOLD and adjusted_stake_fraction > 0.0

    flags = [
        BiasFlag(
            bias_type="overconfidence_oversized_stake", triggered=overconfidence,
            evidence=f"adjusted_stake_fraction={adjusted_stake_fraction:.4f} > {OVERCONFIDENCE_FRACTION_THRESHOLD}",
        ),
        BiasFlag(
            bias_type="fragile_edge_pursuit", triggered=fragile_pursuit,
            evidence=f"robustness_score={robustness_score:.2f} < {FRAGILE_ROBUSTNESS_THRESHOLD} with nonzero stake",
        ),
    ]
    return BiasChecklistResult(passed=not any(f.triggered for f in flags), flags=flags)
