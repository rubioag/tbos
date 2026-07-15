"""TennisDataPlayerStateAdapter — enriches PlayerState with fresher
recent-activity fields from tennis-data.co.uk, on top of a base
StatsSourceAdapter (in practice, SackmannStatsAdapter). It does not
replace the base adapter and cannot run without one, by design: this
source only carries match date/sets/comment, not serve/return stats, so
it structurally cannot answer fetch_player_profile or fetch_match_context
at all, and fetch_player_state only overrides the four fields
tennis-data.co.uk actually evidences.

Overridden fields, only when tennis-data.co.uk resolved at least one
match for the player: matches_last_14d, sets_played_last_14d,
days_since_last_match, injury_flags (from "Retired" losses only, per the
same conservative heuristic style as SackmannStatsAdapter's).

Never touched, always taken from the base record: travel_distance_km,
timezone_shift_hours, deviation_from_baseline. This source has no serve
data, so recomputing deviation_from_baseline from win/loss results alone
would silently redefine what that field means — explicitly out of scope
here (see the provider-selection investigation this adapter followed).

Licensing note: tennis-data.co.uk publishes no explicit reuse license.
This is a documented, known ambiguity — not asserted as confirmed
permission.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    RawMatchContextRecord,
    RawPlayerStateRecord,
    RawPlayerStatsRecord,
    SourceMetadata,
    StatsSourceAdapter,
)
from tbos.data_adapters.player_resolution.resolver import PlayerNameResolver
from tbos.data_adapters.tennis_data.models import TennisDataMatchRow

DATASET_PARSER_VERSION = "tennis-data-co-uk-xlsx-v1"
INJURY_LOOKBACK_DAYS = 30
ACTIVITY_WINDOW_DAYS = 14


class TennisDataPlayerStateAdapter(StatsSourceAdapter):
    source_id = "sackmann_plus_tennis_data_co_uk"

    def __init__(
        self,
        base_adapter: StatsSourceAdapter,
        rows: list[TennisDataMatchRow],
        resolver: PlayerNameResolver,
        *,
        source_trust_score: float = 0.6,
    ) -> None:
        self._base = base_adapter
        self._resolver = resolver
        self._source_trust_score = source_trust_score
        self._by_player: dict[str, list[tuple[TennisDataMatchRow, str]]] = defaultdict(list)
        for row in rows:
            self._attribute(row.winner_name, row, "winner")
            self._attribute(row.loser_name, row, "loser")

    def _attribute(self, name: str, row: TennisDataMatchRow, role: str) -> None:
        try:
            player_id = self._resolver.resolve(name)
        except EntityNotFoundError:
            return  # can't attribute this row to a player_id — skip it, never guess
        self._by_player[player_id].append((row, role))

    def fetch_player_profile(self, player_id: str) -> RawPlayerStatsRecord:
        raise EntityNotFoundError(
            "TennisDataPlayerStateAdapter only supplies PlayerState (recent activity), "
            "never PlayerProfile — use SackmannStatsAdapter for career stats."
        )

    def fetch_match_context(self, match_id: str) -> RawMatchContextRecord:
        raise EntityNotFoundError(
            "TennisDataPlayerStateAdapter does not supply MatchContext."
        )

    def fetch_player_state(self, player_id: str) -> RawPlayerStateRecord:
        base_record = self._base.fetch_player_state(player_id)

        entries = self._by_player.get(player_id)
        if not entries:
            return base_record  # no fresher evidence — honest fallback, not an error

        as_of = datetime.now(UTC)
        as_of_date = as_of.date()

        recent = [(row, role) for row, role in entries if row.match_date <= as_of_date]
        if not recent:
            return base_record

        cutoff_activity = as_of_date - timedelta(days=ACTIVITY_WINDOW_DAYS)
        cutoff_injury = as_of_date - timedelta(days=INJURY_LOOKBACK_DAYS)

        matches_last_14d = sum(1 for row, _ in recent if cutoff_activity <= row.match_date)
        sets_played_last_14d = sum(
            (self._sets_won(row, role) or 0)
            for row, role in recent
            if cutoff_activity <= row.match_date
        )
        days_since_last_match = (as_of_date - max(row.match_date for row, _ in recent)).days

        injury_flags = [
            self._injury_flag(row)
            for row, role in recent
            if role == "loser" and row.comment == "Retired" and cutoff_injury <= row.match_date
        ]

        return base_record.model_copy(update={
            "matches_last_14d": matches_last_14d,
            "sets_played_last_14d": sets_played_last_14d,
            "days_since_last_match": days_since_last_match,
            "injury_flags": injury_flags,
            "metadata": SourceMetadata(
                source_id=self.source_id, collected_at=as_of, parser_version=DATASET_PARSER_VERSION,
                source_priority_rank=1, source_trust_score=self._source_trust_score,
            ),
        })

    @staticmethod
    def _sets_won(row: TennisDataMatchRow, role: str) -> int | None:
        return row.winner_sets if role == "winner" else row.loser_sets

    @staticmethod
    def _injury_flag(row: TennisDataMatchRow) -> dict:
        return {
            "body_part": "unknown", "severity": "MINOR",
            "reported_at": row.match_date.isoformat(),
            "source": "tennis_data_co_uk_retirement_heuristic",
        }
