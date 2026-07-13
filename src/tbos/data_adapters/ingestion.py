"""Wires a StatsSourceAdapter/OddsSourceAdapter into CE.1's real
ingestion pipeline (RawFieldCandidate -> build_field_envelope -> publish
Snapshot). This is the actual point of building adapters: turning
external data into CE.1-shaped, metadata-wrapped, published facts.

Errors from the adapter (source unreachable, entity unknown) result in
`None` — no snapshot published, never a fabricated one — consistent with
CE.1's "missing is an explicit state, not a silent default" discipline.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.models import Snapshot
from tbos.ce1_data.pipeline import RawFieldCandidate, build_field_envelope
from tbos.ce1_data.schemas import MatchContext, MarketSnapshot, PlayerProfile, PlayerState
from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    OddsSourceAdapter,
    RawOddsQuote,
    SourceMetadata,
    SourceUnavailableError,
    StatsSourceAdapter,
)
from tbos.inf1_config.schemas import DataIngestionConfig
from tbos.inf1_config.taxonomy import InstrumentType

def _always_valid(_: object) -> bool:
    return True


def _candidate(value: object, metadata: SourceMetadata) -> RawFieldCandidate:
    return RawFieldCandidate(
        value=value, source_id=metadata.source_id, collected_at=metadata.collected_at,
        parser_version=metadata.parser_version, source_priority_rank=metadata.source_priority_rank,
        source_trust_score=metadata.source_trust_score,
    )


def _field(
    value: object, metadata: SourceMetadata, *, validate: Callable[[object], bool] = _always_valid,
    freshness_threshold_seconds: float, now: datetime,
) -> FieldEnvelope:
    candidate = _candidate(value, metadata) if value is not None else None
    return build_field_envelope(candidate, validate=validate, freshness_threshold_seconds=freshness_threshold_seconds, now=now)


def _pct(v: object) -> bool:
    return isinstance(v, (int, float)) and 0.0 <= v <= 1.0


def _positive(v: object) -> bool:
    return isinstance(v, (int, float)) and v > 0


def ingest_player_profile(
    session: Session, adapter: StatsSourceAdapter, player_id: str, *,
    config: DataIngestionConfig, config_version_id: uuid.UUID, now: datetime,
) -> Snapshot | None:
    try:
        raw = adapter.fetch_player_profile(player_id)
    except (SourceUnavailableError, EntityNotFoundError):
        return None

    fresh = config.freshness_thresholds.player_static_seconds
    m = raw.metadata
    fields = PlayerProfile(
        player_id=_field(raw.player_id, m, freshness_threshold_seconds=fresh, now=now),
        ranking=_field(raw.ranking, m, validate=_positive, freshness_threshold_seconds=fresh, now=now),
        first_serve_pct_by_surface=_field(raw.first_serve_pct_by_surface, m, freshness_threshold_seconds=fresh, now=now),
        service_points_won_pct_by_surface=_field(raw.service_points_won_pct_by_surface, m, freshness_threshold_seconds=fresh, now=now),
        aces_per_match_by_surface=_field(raw.aces_per_match_by_surface, m, freshness_threshold_seconds=fresh, now=now),
        hold_rate_by_surface=_field(raw.hold_rate_by_surface, m, freshness_threshold_seconds=fresh, now=now),
        return_points_won_pct_by_surface=_field(raw.return_points_won_pct_by_surface, m, freshness_threshold_seconds=fresh, now=now),
        break_points_converted_pct_by_surface=_field(raw.break_points_converted_pct_by_surface, m, freshness_threshold_seconds=fresh, now=now),
        style_tags=_field(raw.style_tags, m, freshness_threshold_seconds=fresh, now=now),
        career_stage=_field(raw.career_stage, m, freshness_threshold_seconds=fresh, now=now),
        h2h_records=_field(raw.h2h_records, m, freshness_threshold_seconds=fresh, now=now),
    )
    return ce1_repository.publish_snapshot(
        session, entity_type="PlayerProfile", entity_id=player_id, fields=fields, config_version_id=config_version_id,
    )


def ingest_player_state(
    session: Session, adapter: StatsSourceAdapter, player_id: str, *,
    config: DataIngestionConfig, config_version_id: uuid.UUID, now: datetime,
) -> Snapshot | None:
    try:
        raw = adapter.fetch_player_state(player_id)
    except (SourceUnavailableError, EntityNotFoundError):
        return None

    fresh = config.freshness_thresholds.player_state_seconds
    m = raw.metadata
    fields = PlayerState(
        player_id=_field(raw.player_id, m, freshness_threshold_seconds=fresh, now=now),
        injury_flags=_field(raw.injury_flags, m, freshness_threshold_seconds=fresh, now=now),
        matches_last_14d=_field(raw.matches_last_14d, m, validate=lambda v: v >= 0, freshness_threshold_seconds=fresh, now=now),
        sets_played_last_14d=_field(raw.sets_played_last_14d, m, validate=lambda v: v >= 0, freshness_threshold_seconds=fresh, now=now),
        travel_distance_km=_field(raw.travel_distance_km, m, validate=lambda v: v >= 0, freshness_threshold_seconds=fresh, now=now),
        timezone_shift_hours=_field(raw.timezone_shift_hours, m, freshness_threshold_seconds=fresh, now=now),
        deviation_from_baseline=_field(raw.deviation_from_baseline, m, freshness_threshold_seconds=fresh, now=now),
        days_since_last_match=_field(raw.days_since_last_match, m, validate=lambda v: v >= 0, freshness_threshold_seconds=fresh, now=now),
    )
    return ce1_repository.publish_snapshot(
        session, entity_type="PlayerState", entity_id=player_id, fields=fields, config_version_id=config_version_id,
    )


def ingest_match_context(
    session: Session, adapter: StatsSourceAdapter, match_id: str, *,
    config: DataIngestionConfig, config_version_id: uuid.UUID, now: datetime,
) -> Snapshot | None:
    try:
        raw = adapter.fetch_match_context(match_id)
    except (SourceUnavailableError, EntityNotFoundError):
        return None

    fresh = config.freshness_thresholds.match_context_seconds
    m = raw.metadata
    fields = MatchContext(
        match_id=_field(raw.match_id, m, freshness_threshold_seconds=fresh, now=now),
        tournament_id=_field(raw.tournament_id, m, freshness_threshold_seconds=fresh, now=now),
        round=_field(raw.round, m, freshness_threshold_seconds=fresh, now=now),
        surface=_field(raw.surface, m, freshness_threshold_seconds=fresh, now=now),
        indoor_outdoor=_field(raw.indoor_outdoor, m, freshness_threshold_seconds=fresh, now=now),
        weather_temp_c=_field(raw.weather_temp_c, m, freshness_threshold_seconds=fresh, now=now),
        weather_wind_kph=_field(raw.weather_wind_kph, m, validate=lambda v: v >= 0, freshness_threshold_seconds=fresh, now=now),
        weather_humidity_pct=_field(raw.weather_humidity_pct, m, validate=lambda v: 0 <= v <= 100, freshness_threshold_seconds=fresh, now=now),
        altitude_m=_field(raw.altitude_m, m, freshness_threshold_seconds=fresh, now=now),
        scheduled_start=_field(raw.scheduled_start, m, freshness_threshold_seconds=fresh, now=now),
        best_of=_field(raw.best_of, m, freshness_threshold_seconds=fresh, now=now),
    )
    return ce1_repository.publish_snapshot(
        session, entity_type="MatchContext", entity_id=match_id, fields=fields, config_version_id=config_version_id,
    )


def ingest_odds(
    session: Session, adapter: OddsSourceAdapter, match_id: str, instrument_type: InstrumentType, *,
    config: DataIngestionConfig, config_version_id: uuid.UUID, now: datetime,
) -> list[Snapshot]:
    try:
        quotes: list[RawOddsQuote] = adapter.fetch_odds(match_id, instrument_type)
    except (SourceUnavailableError, EntityNotFoundError):
        return []

    fresh = config.freshness_thresholds.market_odds_seconds
    snapshots = []
    for quote in quotes:
        m = quote.metadata
        fields = MarketSnapshot(
            match_id=_field(quote.match_id, m, freshness_threshold_seconds=fresh, now=now),
            instrument_type=_field(quote.instrument_type.value, m, freshness_threshold_seconds=fresh, now=now),
            book_id=_field(quote.book_id, m, freshness_threshold_seconds=fresh, now=now),
            odds=_field(quote.odds, m, validate=lambda v: v > 1.0, freshness_threshold_seconds=fresh, now=now),
            implied_probability=_field(1.0 / quote.odds, m, validate=_pct, freshness_threshold_seconds=fresh, now=now),
            liquidity_estimate=_field(0.0, m, freshness_threshold_seconds=fresh, now=now),
            captured_at=_field(quote.captured_at, m, freshness_threshold_seconds=fresh, now=now),
            is_closing_snapshot=_field(False, m, freshness_threshold_seconds=fresh, now=now),
        )
        entity_id = f"{match_id}:{instrument_type.value}:{quote.book_id}"
        snapshots.append(
            ce1_repository.publish_snapshot(
                session, entity_type="MarketSnapshot", entity_id=entity_id, fields=fields, config_version_id=config_version_id,
            )
        )
    return snapshots
