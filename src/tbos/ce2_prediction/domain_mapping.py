"""CE.2.5 — Domain-to-log-odds mapping functions.

Owned exclusively by the Ensemble Aggregator (never by a Model — see the
correction locked into every Model spec: they output domain distributions,
never a probability). Each mapping is a simple, documented, versioned
transform from one Model's `estimate` dict into a single log-odds
contribution favoring player_a (positive) or player_b (negative). Scale
constants are v1 placeholders, tunable via config once real backtest data
exists — hardcoded here only because that data doesn't exist yet.
"""

from __future__ import annotations

import math
from collections.abc import Callable

SERVE_LOG_ODDS_SCALE = 2.0
RETURN_LOG_ODDS_SCALE = 2.0
SURFACE_LOG_ODDS_SCALE = 3.0
FORM_FATIGUE_LOG_ODDS_SCALE = 4.0
MATCHUP_LOG_ODDS_SCALE = 1.0

_LOGIT_EPS = 1e-4


def logit(p: float) -> float:
    p = min(max(p, _LOGIT_EPS), 1 - _LOGIT_EPS)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _serve_mapping(estimate: dict) -> float:
    diff = estimate["player_a"]["hold_probability"] - estimate["player_b"]["hold_probability"]
    return diff * SERVE_LOG_ODDS_SCALE


def _return_mapping(estimate: dict) -> float:
    diff = estimate["player_a"]["return_points_won_pct"] - estimate["player_b"]["return_points_won_pct"]
    return diff * RETURN_LOG_ODDS_SCALE


def _surface_mapping(estimate: dict) -> float:
    diff = estimate["player_a"]["surface_adjustment"] - estimate["player_b"]["surface_adjustment"]
    return diff * SURFACE_LOG_ODDS_SCALE


def _form_fatigue_mapping(estimate: dict) -> float:
    diff = estimate["player_a"]["net_adjustment"] - estimate["player_b"]["net_adjustment"]
    return diff * FORM_FATIGUE_LOG_ODDS_SCALE


def _matchup_mapping(estimate: dict) -> float:
    return logit(estimate["h2h_win_rate_player_a"]) * MATCHUP_LOG_ODDS_SCALE


DOMAIN_MAPPINGS: dict[str, Callable[[dict], float]] = {
    "serve": _serve_mapping,
    "return": _return_mapping,
    "surface": _surface_mapping,
    "form_fatigue": _form_fatigue_mapping,
    "matchup": _matchup_mapping,
}


class UnknownDomainError(KeyError):
    pass


def map_to_log_odds(domain: str, estimate: dict) -> float:
    if domain not in DOMAIN_MAPPINGS:
        raise UnknownDomainError(f"no domain-to-log-odds mapping registered for domain {domain!r}")
    return DOMAIN_MAPPINGS[domain](estimate)
