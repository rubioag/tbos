"""CE.3 — Expected Value Distribution (spec §1: EV is a distribution,
never a single number). Uncertainty from CE.2 is propagated by shifting
the probability up/down within its own uncertainty band before recomputing
EV, rather than reporting a single point estimate.
"""

from __future__ import annotations

from pydantic import BaseModel


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def ev_value(probability: float, offered_odds: float) -> float:
    return probability * offered_odds - 1.0


class EVDistribution(BaseModel):
    expected: float
    best_case: float
    worst_case: float
    confidence_interval: tuple[float, float]


def compute_ev_distribution(probability: float, uncertainty: float, offered_odds: float) -> EVDistribution:
    if offered_odds <= 1.0:
        raise ValueError(f"offered_odds must be > 1.0, got {offered_odds}")

    p_low = clamp01(probability - uncertainty)
    p_high = clamp01(probability + uncertainty)

    expected = ev_value(probability, offered_odds)
    worst_case = ev_value(p_low, offered_odds)
    best_case = ev_value(p_high, offered_odds)

    return EVDistribution(
        expected=expected, best_case=best_case, worst_case=worst_case,
        confidence_interval=(worst_case, best_case),
    )
