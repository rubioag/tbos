"""Shared test-only factories for building ModelInputBundle fixtures.
Not part of the src/ package — test infrastructure only.
"""

from __future__ import annotations

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import MatchContext, PlayerProfile, PlayerState
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.inf1_config.taxonomy import (
    BestOf,
    FieldAvailability,
    FieldValidity,
    InformationReliability,
    Surface,
)
from datetime import datetime, timezone


def env(value: object) -> FieldEnvelope:
    return FieldEnvelope(
        value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
    )


def missing_env() -> FieldEnvelope:
    return FieldEnvelope.missing()


def make_profile(
    player_id: str = "p1",
    *,
    hold_rate: dict[str, float] | None = None,
    service_points_won: dict[str, float] | None = None,
    aces: dict[str, float] | None = None,
    return_points_won: dict[str, float] | None = None,
    break_conversion: dict[str, float] | None = None,
    first_serve: dict[str, float] | None = None,
) -> PlayerProfile:
    return PlayerProfile(
        player_id=env(player_id),
        ranking=env(10),
        first_serve_pct_by_surface=env(first_serve or {"HARD": 0.62}),
        service_points_won_pct_by_surface=env(service_points_won or {"HARD": 0.65}),
        aces_per_match_by_surface=env(aces or {"HARD": 8.0}),
        hold_rate_by_surface=env(hold_rate or {"HARD": 0.80}),
        return_points_won_pct_by_surface=env(return_points_won or {"HARD": 0.35}),
        break_points_converted_pct_by_surface=env(break_conversion or {"HARD": 0.38}),
        style_tags=env(["baseline"]),
        career_stage=env("PEAK"),
        h2h_records=env([]),
    )


def make_state(
    player_id: str = "p1",
    *,
    injury_flags: list[dict] | None = None,
    matches_last_14d: float = 3,
    sets_played_last_14d: float = 7,
    deviation_from_baseline: float = 0.0,
    days_since_last_match: float = 4,
) -> PlayerState:
    return PlayerState(
        player_id=env(player_id), injury_flags=env(injury_flags if injury_flags is not None else []),
        matches_last_14d=env(matches_last_14d), sets_played_last_14d=env(sets_played_last_14d),
        travel_distance_km=env(0.0), timezone_shift_hours=env(0.0),
        deviation_from_baseline=env(deviation_from_baseline), days_since_last_match=env(days_since_last_match),
    )


def make_match_context(surface: Surface = Surface.HARD) -> MatchContext:
    return MatchContext(
        match_id=env("match_1"), tournament_id=env("t1"), round=env("QF"),
        surface=env(surface), indoor_outdoor=env("OUTDOOR"),
        weather_temp_c=env(24.0), weather_wind_kph=env(5.0), weather_humidity_pct=env(40.0),
        altitude_m=env(50.0), scheduled_start=env(datetime.now(timezone.utc)), best_of=env(BestOf.BO3),
    )


def make_bundle(
    *,
    player_a_profile: PlayerProfile | None = None,
    player_b_profile: PlayerProfile | None = None,
    player_a_state: PlayerState | None = None,
    player_b_state: PlayerState | None = None,
    match_context: MatchContext | None = None,
    include_states: bool = False,
) -> ModelInputBundle:
    if include_states:
        player_a_state = player_a_state if player_a_state is not None else make_state("p1")
        player_b_state = player_b_state if player_b_state is not None else make_state("p2")

    return ModelInputBundle(
        match_id="match_1", player_a_id="p1", player_b_id="p2",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        player_a_profile=player_a_profile if player_a_profile is not None else make_profile("p1"),
        player_b_profile=player_b_profile if player_b_profile is not None else make_profile("p2"),
        player_a_state=player_a_state,
        player_b_state=player_b_state,
        match_context=match_context if match_context is not None else make_match_context(),
    )
