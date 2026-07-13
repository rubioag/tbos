"""CE.4 — Stake Sizing. Fractional Kelly, discounted by CE.3's own
Robustness and CE.2's own Uncertainty — a fragile or uncertain edge gets a
smaller stake even at equal expected EV (spec §C).
"""

from __future__ import annotations

from pydantic import BaseModel


def kelly_fraction(probability: float, offered_odds: float) -> float:
    """f* = (b*p - q) / b, b = net odds. Never negative — a Kelly-negative
    edge means "don't bet", clamped to 0.0 rather than a short position.
    """
    b = offered_odds - 1.0
    q = 1.0 - probability
    f = (b * probability - q) / b
    return max(0.0, f)


class StakeResult(BaseModel):
    raw_kelly_fraction: float
    adjusted_fraction: float
    stake_amount: float


def compute_stake(
    *,
    bankroll_total: float,
    probability: float,
    offered_odds: float,
    robustness_score: float,
    uncertainty: float,
    fractional_kelly_multiplier: float,
) -> StakeResult:
    raw = kelly_fraction(probability, offered_odds)
    uncertainty_discount = max(0.0, 1.0 - uncertainty)
    adjusted = raw * fractional_kelly_multiplier * robustness_score * uncertainty_discount
    return StakeResult(
        raw_kelly_fraction=raw, adjusted_fraction=adjusted, stake_amount=bankroll_total * adjusted,
    )
