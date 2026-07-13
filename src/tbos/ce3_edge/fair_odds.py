"""CE.3 — Probability -> Fair Odds. Pure conversion, no market comparison
here (Market Independence Principle: this module never looks at offered
odds, only converts CE.2's probability into what a zero-vig book would offer).
"""

from __future__ import annotations


def fair_odds_from_probability(probability: float) -> float:
    if not (0.0 < probability < 1.0):
        raise ValueError(f"probability must be strictly between 0 and 1, got {probability}")
    return 1.0 / probability
