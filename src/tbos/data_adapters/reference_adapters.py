"""Reference adapters: in-memory, deterministic, no network calls.
Proves the contract end-to-end and is genuinely usable for local dev/demo
without any real provider credentials. A real provider swaps in later by
implementing the same ABCs — nothing else in the system changes.
"""

from __future__ import annotations

from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    OddsSourceAdapter,
    RawMatchContextRecord,
    RawOddsQuote,
    RawPlayerStateRecord,
    RawPlayerStatsRecord,
    StatsSourceAdapter,
    SourceUnavailableError,
)
from tbos.inf1_config.taxonomy import InstrumentType


class InMemoryStatsAdapter(StatsSourceAdapter):
    source_id = "reference_stats_adapter"

    def __init__(
        self,
        *,
        profiles: dict[str, RawPlayerStatsRecord] | None = None,
        states: dict[str, RawPlayerStateRecord] | None = None,
        contexts: dict[str, RawMatchContextRecord] | None = None,
        unavailable: bool = False,
    ) -> None:
        self._profiles = profiles or {}
        self._states = states or {}
        self._contexts = contexts or {}
        self._unavailable = unavailable

    def fetch_player_profile(self, player_id: str) -> RawPlayerStatsRecord:
        if self._unavailable:
            raise SourceUnavailableError(self.source_id)
        record = self._profiles.get(player_id)
        if record is None:
            raise EntityNotFoundError(f"no player profile for {player_id!r}")
        return record

    def fetch_player_state(self, player_id: str) -> RawPlayerStateRecord:
        if self._unavailable:
            raise SourceUnavailableError(self.source_id)
        record = self._states.get(player_id)
        if record is None:
            raise EntityNotFoundError(f"no player state for {player_id!r}")
        return record

    def fetch_match_context(self, match_id: str) -> RawMatchContextRecord:
        if self._unavailable:
            raise SourceUnavailableError(self.source_id)
        record = self._contexts.get(match_id)
        if record is None:
            raise EntityNotFoundError(f"no match context for {match_id!r}")
        return record


class InMemoryOddsAdapter(OddsSourceAdapter):
    source_id = "reference_odds_adapter"

    def __init__(self, *, quotes: list[RawOddsQuote] | None = None, unavailable: bool = False) -> None:
        self._quotes = quotes or []
        self._unavailable = unavailable

    def fetch_odds(self, match_id: str, instrument_type: InstrumentType) -> list[RawOddsQuote]:
        if self._unavailable:
            raise SourceUnavailableError(self.source_id)
        matches = [q for q in self._quotes if q.match_id == match_id and q.instrument_type == instrument_type]
        if not matches:
            raise EntityNotFoundError(f"no odds for match={match_id!r} instrument={instrument_type!r}")
        return matches
