"""CE.6 — Closing Line Value calculation. Vig removal needs both sides'
odds (a single side's implied probability always includes the book's
margin, unremovable alone). Our built pipeline doesn't track the
opposite side's odds anywhere yet, so `opponent_odds` is optional here:
supplied -> proportional vig-adjustment; omitted -> raw implied
probability, honestly flagged `vig_adjusted=False` rather than faking a
removal with data that doesn't exist.

CLV convention: positive clv_value means the closing implied probability
is HIGHER than the implied probability we got at placement — the market
moved to agree with us after we bet, i.e. we beat the closing line.
"""

from __future__ import annotations

from pydantic import BaseModel


def implied_probability(odds: float) -> float:
    if odds <= 1.0:
        raise ValueError(f"odds must be > 1.0, got {odds}")
    return 1.0 / odds


class ProbabilityResult(BaseModel):
    probability: float
    vig_adjusted: bool


def vig_adjusted_probability(
    odds: float, opponent_odds: float | None, *, method: str = "proportional"
) -> ProbabilityResult:
    raw = implied_probability(odds)
    if opponent_odds is None:
        return ProbabilityResult(probability=raw, vig_adjusted=False)

    opponent_raw = implied_probability(opponent_odds)
    if method != "proportional":
        raise ValueError(f"unknown vig_adjustment_method {method!r}")

    total = raw + opponent_raw
    return ProbabilityResult(probability=raw / total, vig_adjusted=True)


class CLVCalculation(BaseModel):
    placed_implied_probability: float
    closing_implied_probability: float
    clv_value: float
    vig_adjusted: bool


def compute_clv(
    *,
    placed_odds: float,
    closing_odds: float,
    placed_opponent_odds: float | None = None,
    closing_opponent_odds: float | None = None,
    vig_adjustment_method: str = "proportional",
) -> CLVCalculation:
    placed = vig_adjusted_probability(placed_odds, placed_opponent_odds, method=vig_adjustment_method)
    closing = vig_adjusted_probability(closing_odds, closing_opponent_odds, method=vig_adjustment_method)

    return CLVCalculation(
        placed_implied_probability=placed.probability,
        closing_implied_probability=closing.probability,
        clv_value=closing.probability - placed.probability,
        vig_adjusted=placed.vig_adjusted and closing.vig_adjusted,
    )
