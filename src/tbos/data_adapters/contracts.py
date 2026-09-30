"""Generic adapter contract for external data sources — stats/results
providers and odds providers. A real provider (Sportradar, The Odds API,
etc.) implements these ABCs; nothing downstream (ingestion.py, CE.1)
needs to know which concrete provider is behind the interface.

Errors are explicit and typed so the ingestion layer can distinguish
"this entity doesn't exist" from "the source is temporarily unreachable"
— both result in MISSING data, never a fabricated value, but the
distinction matters for observability/retry policy later.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel

from tbos.inf1_config.taxonomy import InstrumentType


class SourceUnavailableError(RuntimeError):
    """The source could not be reached at all (network, auth, rate limit)."""


class EntityNotFoundError(RuntimeError):
    """The source was reachable but has no record for the requested entity."""


class SourceMetadata(BaseModel):
    source_id: str
    collected_at: datetime
    parser_version: str
    source_priority_rank: int
    source_trust_score: float


class RawPlayerStatsRecord(BaseModel):
    player_id: str
    ranking: int | None
    first_serve_pct_by_surface: dict[str, float]
    service_points_won_pct_by_surface: dict[str, float]
    aces_per_match_by_surface: dict[str, float]
    hold_rate_by_surface: dict[str, float]
    return_points_won_pct_by_surface: dict[str, float]
    break_points_converted_pct_by_surface: dict[str, float]
    style_tags: list[str]
    career_stage: str
    h2h_records: list[dict]
    elo_rating: float
    elo_rating_by_surface: dict[str, float]
    metadata: SourceMetadata


class RawPlayerStateRecord(BaseModel):
    player_id: str
    injury_flags: list[dict]
    matches_last_14d: int
    sets_played_last_14d: int
    travel_distance_km: float
    timezone_shift_hours: float
    deviation_from_baseline: float
    days_since_last_match: int
    metadata: SourceMetadata


class RawMatchContextRecord(BaseModel):
    match_id: str
    tournament_id: str
    round: str
    surface: str
    indoor_outdoor: str
    weather_temp_c: float
    weather_wind_kph: float
    weather_humidity_pct: float
    altitude_m: float
    scheduled_start: datetime
    best_of: str
    metadata: SourceMetadata


class RawOddsQuote(BaseModel):
    match_id: str
    instrument_type: InstrumentType
    book_id: str
    # Which side of the market `odds` prices. Required (no default): a
    # two-outcome market (e.g. moneyline) always yields two quotes per
    # book, and silently defaulting this would let them collide under
    # the same entity_id in ingestion. "player_a"/"player_b" are the
    # only values in v1 — matches the two-competitor tennis match model.
    selection: str
    odds: float
    captured_at: datetime
    metadata: SourceMetadata


class StatsSourceAdapter(ABC):
    source_id: ClassVar[str]

    @abstractmethod
    def fetch_player_profile(self, player_id: str) -> RawPlayerStatsRecord: ...

    @abstractmethod
    def fetch_player_state(self, player_id: str) -> RawPlayerStateRecord: ...

    @abstractmethod
    def fetch_match_context(self, match_id: str) -> RawMatchContextRecord: ...


class OddsSourceAdapter(ABC):
    source_id: ClassVar[str]

    @abstractmethod
    def fetch_odds(self, match_id: str, instrument_type: InstrumentType) -> list[RawOddsQuote]: ...
