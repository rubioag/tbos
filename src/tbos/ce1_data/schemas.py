"""CE.1 — the four published entity schemas. Every field is a
FieldEnvelope; there is no raw/unwrapped field anywhere in these models.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.inf1_config.taxonomy import BestOf, InstrumentType, Surface


class PlayerProfile(BaseModel):
    player_id: FieldEnvelope[str]
    ranking: FieldEnvelope[int]
    first_serve_pct_by_surface: FieldEnvelope[dict[str, float]]
    service_points_won_pct_by_surface: FieldEnvelope[dict[str, float]]
    aces_per_match_by_surface: FieldEnvelope[dict[str, float]]
    hold_rate_by_surface: FieldEnvelope[dict[str, float]]
    return_points_won_pct_by_surface: FieldEnvelope[dict[str, float]]
    break_points_converted_pct_by_surface: FieldEnvelope[dict[str, float]]
    style_tags: FieldEnvelope[list[str]]
    career_stage: FieldEnvelope[str]
    h2h_records: FieldEnvelope[list[dict]]


class PlayerState(BaseModel):
    player_id: FieldEnvelope[str]
    injury_flags: FieldEnvelope[list[dict]]
    matches_last_14d: FieldEnvelope[int]
    sets_played_last_14d: FieldEnvelope[int]
    travel_distance_km: FieldEnvelope[float]
    timezone_shift_hours: FieldEnvelope[float]
    deviation_from_baseline: FieldEnvelope[float]
    days_since_last_match: FieldEnvelope[int]


class MatchContext(BaseModel):
    match_id: FieldEnvelope[str]
    tournament_id: FieldEnvelope[str]
    round: FieldEnvelope[str]
    surface: FieldEnvelope[Surface]
    indoor_outdoor: FieldEnvelope[str]
    weather_temp_c: FieldEnvelope[float]
    weather_wind_kph: FieldEnvelope[float]
    weather_humidity_pct: FieldEnvelope[float]
    altitude_m: FieldEnvelope[float]
    scheduled_start: FieldEnvelope[datetime]
    best_of: FieldEnvelope[BestOf]


class MarketSnapshot(BaseModel):
    match_id: FieldEnvelope[str]
    instrument_type: FieldEnvelope[InstrumentType]
    book_id: FieldEnvelope[str]
    odds: FieldEnvelope[float]
    implied_probability: FieldEnvelope[float]
    liquidity_estimate: FieldEnvelope[float]
    captured_at: FieldEnvelope[datetime]
    is_closing_snapshot: FieldEnvelope[bool]


ENTITY_SCHEMAS: dict[str, type[BaseModel]] = {
    "PlayerProfile": PlayerProfile,
    "PlayerState": PlayerState,
    "MatchContext": MatchContext,
    "MarketSnapshot": MarketSnapshot,
}
