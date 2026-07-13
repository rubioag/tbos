"""CE.4 — Ruin-Risk Check. Monte Carlo simulation of repeated betting at
the proposed stake fraction, estimating probability of hitting zero
bankroll before a fixed horizon. `rng_seed` makes results reproducible
for tests; production use should leave it unset (or vary per run).
"""

from __future__ import annotations

import random

from pydantic import BaseModel

DEFAULT_SIMULATED_PATHS = 1000
DEFAULT_HORIZON_BETS = 50
# Under proportional (stake = balance * fraction) staking, balance decays
# geometrically toward zero but can never mathematically reach it — a
# `balance <= 0` ruin check would never fire regardless of how bad the
# edge is. Ruin is instead defined the standard way for Kelly-style
# simulations: balance falling below a small fraction of the starting
# bankroll.
DEFAULT_RUIN_THRESHOLD_FRACTION = 0.05


class RuinRiskResult(BaseModel):
    ruin_probability: float
    passed: bool
    simulated_paths: int


def simulate_ruin_risk(
    *,
    stake_fraction: float,
    probability: float,
    offered_odds: float,
    max_ruin_probability: float,
    simulated_paths: int = DEFAULT_SIMULATED_PATHS,
    horizon_bets: int = DEFAULT_HORIZON_BETS,
    ruin_threshold_fraction: float = DEFAULT_RUIN_THRESHOLD_FRACTION,
    rng_seed: int | None = None,
) -> RuinRiskResult:
    rng = random.Random(rng_seed)
    net_odds = offered_odds - 1.0
    ruin_count = 0

    for _ in range(simulated_paths):
        balance = 1.0
        for _ in range(horizon_bets):
            bet = balance * stake_fraction
            if rng.random() < probability:
                balance += bet * net_odds
            else:
                balance -= bet
            if balance <= ruin_threshold_fraction:
                ruin_count += 1
                break

    ruin_probability = ruin_count / simulated_paths if simulated_paths else 0.0
    return RuinRiskResult(
        ruin_probability=ruin_probability, passed=ruin_probability < max_ruin_probability,
        simulated_paths=simulated_paths,
    )
