"""PlayerState-facing derived metrics: recent match load, days rest, form
deviation, and a best-effort injury heuristic from retirement scores.

`travel_distance_km` / `timezone_shift_hours` are NOT computed here —
Sackmann match rows carry no venue geocoordinates, and fabricating them
would violate the no-fabrication discipline that runs through this whole
system. Callers get 0.0 for those fields with the field's own metadata
honestly reflecting that it is not derivable from this source.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from tbos.data_adapters.sackmann.models import MatchRow

_SET_SCORE_RE = re.compile(r"^\d+-\d+")


def _player_matches(matches: list[MatchRow], player_id: str) -> list[MatchRow]:
    return [m for m in matches if m.winner_id == player_id or m.loser_id == player_id]


def count_sets_in_score(score: str | None) -> int:
    if not score:
        return 0
    tokens = score.split()
    return sum(1 for t in tokens if _SET_SCORE_RE.match(t))


def compute_matches_last_n_days(matches: list[MatchRow], player_id: str, *, as_of: date, days: int = 14) -> int:
    cutoff = as_of - timedelta(days=days)
    return sum(1 for m in _player_matches(matches, player_id) if cutoff <= m.tourney_date <= as_of)


def compute_sets_played_last_n_days(matches: list[MatchRow], player_id: str, *, as_of: date, days: int = 14) -> int:
    cutoff = as_of - timedelta(days=days)
    return sum(
        count_sets_in_score(m.score)
        for m in _player_matches(matches, player_id)
        if cutoff <= m.tourney_date <= as_of
    )


def compute_days_since_last_match(matches: list[MatchRow], player_id: str, *, as_of: date) -> int | None:
    past = [m.tourney_date for m in _player_matches(matches, player_id) if m.tourney_date <= as_of]
    if not past:
        return None
    return (as_of - max(past)).days


def compute_deviation_from_baseline(
    matches: list[MatchRow], player_id: str, *, as_of: date, recent_match_count: int = 10,
) -> float | None:
    """Recent serving performance minus this player's own career-average
    serving performance — a continuous form signal, deliberately not a
    win/loss streak (per the "momentum" correction already locked at
    Form/Fatigue Model design time).
    """
    from tbos.data_adapters.sackmann.aggregator import (  # local import, avoids a cycle at module load
        get_stat,
        pair_prefixes,
    )

    played = sorted(
        (m for m in _player_matches(matches, player_id) if m.tourney_date <= as_of),
        key=lambda m: m.tourney_date,
    )
    if not played:
        return None

    def _serve_rate(match: MatchRow) -> float | None:
        prefixes = pair_prefixes(match, player_id)
        if prefixes is None:
            return None
        own, _ = prefixes
        svpt, first_won, second_won = get_stat(match, own, "svpt"), get_stat(match, own, "1stWon"), get_stat(match, own, "2ndWon")
        if not svpt or None in (first_won, second_won):
            return None
        return (first_won + second_won) / svpt

    career_rates = [r for m in played if (r := _serve_rate(m)) is not None]
    if not career_rates:
        return None
    career_baseline = sum(career_rates) / len(career_rates)

    recent_rates = career_rates[-recent_match_count:]
    recent_avg = sum(recent_rates) / len(recent_rates)

    return recent_avg - career_baseline


def detect_injury_flags(
    matches: list[MatchRow], player_id: str, *, as_of: date, lookback_days: int = 30,
) -> list[dict]:
    """Best-effort heuristic: a recent match this player LOST via
    retirement ("RET" in the score) is flagged as a possible injury.
    Severity is unknown from this data — tagged MINOR as the conservative
    default rather than guessing higher, and the source is explicit so
    downstream consumers can discount it accordingly.
    """
    cutoff = as_of - timedelta(days=lookback_days)
    flags: list[dict] = []
    for m in matches:
        if not (cutoff <= m.tourney_date <= as_of):
            continue
        if m.loser_id != player_id:
            continue
        if m.score and "RET" in m.score.upper():
            flags.append({
                "body_part": "unknown", "severity": "MINOR",
                "reported_at": m.tourney_date.isoformat(), "source": "sackmann_retirement_heuristic",
            })
    return flags
