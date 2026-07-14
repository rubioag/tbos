"""SackmannStatsAdapter — implements the existing StatsSourceAdapter
contract (CE.1 ingestion, unchanged) entirely from locally-aggregated
historical match data. No network calls, no new provider dependency.

`fetch_match_context` is intentionally unsupported: Sackmann's dataset is
historical match results, not future fixtures — it structurally cannot
answer "what match is scheduled next." MatchContext for upcoming matches
must come from the odds provider (The Odds API's event metadata) instead;
this is a real, documented boundary of what this adapter can do, not a bug.

`fetch_player_profile`/`fetch_player_state` always compute "as of now" —
the StatsSourceAdapter ABC takes only `player_id`, no `as_of`, so this
adapter cannot be used for historical backtest reconstruction (that needs
the Historical Data Pipeline's anti-lookahead machinery instead). It is
built for live Paper Trading ingestion: aggregate everything known up to
the moment of the call.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    RawMatchContextRecord,
    RawPlayerStateRecord,
    RawPlayerStatsRecord,
    SourceMetadata,
    StatsSourceAdapter,
)
from tbos.data_adapters.sackmann.aggregator import compute_serve_return_by_surface
from tbos.data_adapters.sackmann.h2h import compute_h2h_records
from tbos.data_adapters.sackmann.models import MatchRow
from tbos.data_adapters.sackmann.player_state import (
    compute_days_since_last_match,
    compute_deviation_from_baseline,
    compute_matches_last_n_days,
    compute_sets_played_last_n_days,
    detect_injury_flags,
)

DATASET_PARSER_VERSION = "sackmann-csv-v1"

_REQUIRED_SURFACE_KEYS = (
    "first_serve_pct", "service_points_won_pct", "aces_per_match", "hold_rate",
    "return_points_won_pct", "break_points_converted_pct",
)


def _most_recent_match(matches: list[MatchRow], player_id: str, *, as_of: date) -> MatchRow | None:
    candidates = [m for m in matches if (m.winner_id == player_id or m.loser_id == player_id) and m.tourney_date <= as_of]
    return max(candidates, key=lambda m: m.tourney_date) if candidates else None


def _career_stage_from_age(age: float | None) -> str:
    if age is None:
        return "UNKNOWN"
    if age < 23:
        return "RISING"
    if age <= 30:
        return "PEAK"
    return "DECLINING"


class SackmannStatsAdapter(StatsSourceAdapter):
    source_id = "sackmann_local_dataset"

    def __init__(self, matches: list[MatchRow], *, source_trust_score: float = 0.85) -> None:
        self._matches = matches
        self._source_trust_score = source_trust_score

    def _metadata(self, as_of: datetime) -> SourceMetadata:
        return SourceMetadata(
            source_id=self.source_id, collected_at=as_of, parser_version=DATASET_PARSER_VERSION,
            source_priority_rank=1, source_trust_score=self._source_trust_score,
        )

    def fetch_player_profile(self, player_id: str) -> RawPlayerStatsRecord:
        as_of = datetime.now(timezone.utc)
        as_of_date = as_of.date()

        by_surface = compute_serve_return_by_surface(self._matches, player_id, as_of=as_of_date)
        if not by_surface:
            raise EntityNotFoundError(f"no Sackmann match history for player_id={player_id!r} as of {as_of_date}")

        recent_match = _most_recent_match(self._matches, player_id, as_of=as_of_date)
        assert recent_match is not None  # by_surface non-empty implies at least one match exists

        if recent_match.winner_id == player_id:
            hand, age = recent_match.winner_hand, recent_match.winner_age
            ranking = recent_match.winner_rank
            name = recent_match.winner_name
        else:
            hand, age = recent_match.loser_hand, recent_match.loser_age
            ranking = recent_match.loser_rank
            name = recent_match.loser_name

        style_tags = []
        if hand == "L":
            style_tags.append("left-handed")
        elif hand == "R":
            style_tags.append("right-handed")

        def _field(key: str) -> dict[str, float]:
            return {surface: stats[key] for surface, stats in by_surface.items() if key in stats}

        return RawPlayerStatsRecord(
            player_id=player_id,
            ranking=ranking,
            first_serve_pct_by_surface=_field("first_serve_pct"),
            service_points_won_pct_by_surface=_field("service_points_won_pct"),
            aces_per_match_by_surface=_field("aces_per_match"),
            hold_rate_by_surface=_field("hold_rate"),
            return_points_won_pct_by_surface=_field("return_points_won_pct"),
            break_points_converted_pct_by_surface=_field("break_points_converted_pct"),
            style_tags=style_tags,
            career_stage=_career_stage_from_age(age),
            h2h_records=compute_h2h_records(self._matches, player_id, as_of=as_of_date),
            metadata=self._metadata(as_of),
        )

    def fetch_player_state(self, player_id: str) -> RawPlayerStateRecord:
        as_of = datetime.now(timezone.utc)
        as_of_date = as_of.date()

        if _most_recent_match(self._matches, player_id, as_of=as_of_date) is None:
            raise EntityNotFoundError(f"no Sackmann match history for player_id={player_id!r} as of {as_of_date}")

        deviation = compute_deviation_from_baseline(self._matches, player_id, as_of=as_of_date)
        days_since = compute_days_since_last_match(self._matches, player_id, as_of=as_of_date)

        return RawPlayerStateRecord(
            player_id=player_id,
            injury_flags=detect_injury_flags(self._matches, player_id, as_of=as_of_date),
            matches_last_14d=compute_matches_last_n_days(self._matches, player_id, as_of=as_of_date, days=14),
            sets_played_last_14d=compute_sets_played_last_n_days(self._matches, player_id, as_of=as_of_date, days=14),
            travel_distance_km=0.0,   # not derivable from Sackmann data — see module docstring
            timezone_shift_hours=0.0,  # not derivable from Sackmann data
            deviation_from_baseline=deviation if deviation is not None else 0.0,
            days_since_last_match=days_since if days_since is not None else 0,
            metadata=self._metadata(as_of),
        )

    def fetch_match_context(self, match_id: str) -> RawMatchContextRecord:
        raise EntityNotFoundError(
            "SackmannStatsAdapter cannot supply MatchContext — the dataset is historical results only, "
            "with no future fixtures. Use the odds provider's event metadata for MatchContext instead."
        )
