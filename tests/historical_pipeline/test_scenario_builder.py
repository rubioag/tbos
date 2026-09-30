import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import MatchContext, PlayerProfile, PlayerState
from tbos.historical_pipeline import market_history
from tbos.historical_pipeline.scenario_builder import build_scenario
from tbos.inf1_config.taxonomy import (
    BestOf,
    FieldAvailability,
    FieldValidity,
    InformationReliability,
    InstrumentType,
    Surface,
)

CONFIG_VERSION_ID = uuid.uuid4()
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _env(value: object) -> FieldEnvelope:
    return FieldEnvelope(
        value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
    )


def _profile() -> PlayerProfile:
    return PlayerProfile(
        player_id=_env("p1"), ranking=_env(5),
        first_serve_pct_by_surface=_env({"HARD": 0.62}),
        service_points_won_pct_by_surface=_env({"HARD": 0.71}),
        aces_per_match_by_surface=_env({"HARD": 8.2}),
        hold_rate_by_surface=_env({"HARD": 0.85}),
        return_points_won_pct_by_surface=_env({"HARD": 0.38}),
        break_points_converted_pct_by_surface=_env({"HARD": 0.41}),
        style_tags=_env(["baseline"]), career_stage=_env("PEAK"), h2h_records=_env([]),
        elo_rating=_env(1500.0), elo_rating_by_surface=_env({"HARD": 1500.0}),
    )


def _state() -> PlayerState:
    return PlayerState(
        player_id=_env("p1"), injury_flags=_env([]), matches_last_14d=_env(3),
        sets_played_last_14d=_env(7), travel_distance_km=_env(0.0),
        timezone_shift_hours=_env(0.0), deviation_from_baseline=_env(0.0),
        days_since_last_match=_env(4),
    )


def _match_context() -> MatchContext:
    return MatchContext(
        match_id=_env("match_1"), tournament_id=_env("t1"), round=_env("QF"),
        surface=_env(Surface.HARD), indoor_outdoor=_env("OUTDOOR"),
        weather_temp_c=_env(24.0), weather_wind_kph=_env(5.0), weather_humidity_pct=_env(40.0),
        altitude_m=_env(50.0), scheduled_start=_env(T0), best_of=_env(BestOf.BO3),
    )


def test_build_scenario_assembles_all_references(session: Session) -> None:
    ce1_repository.publish_snapshot(
        session, entity_type="PlayerProfile", entity_id="p1", fields=_profile(), config_version_id=CONFIG_VERSION_ID
    )
    ce1_repository.publish_snapshot(
        session, entity_type="PlayerState", entity_id="p1", fields=_state(), config_version_id=CONFIG_VERSION_ID
    )
    ce1_repository.publish_snapshot(
        session, entity_type="PlayerProfile", entity_id="p2", fields=_profile(), config_version_id=CONFIG_VERSION_ID
    )
    ce1_repository.publish_snapshot(
        session, entity_type="PlayerState", entity_id="p2", fields=_state(), config_version_id=CONFIG_VERSION_ID
    )
    ce1_repository.publish_snapshot(
        session, entity_type="MatchContext", entity_id="match_1", fields=_match_context(),
        config_version_id=CONFIG_VERSION_ID,
    )
    market_history.append_tick(
        session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a",
        odds=1.85, tick_timestamp=T0 - timedelta(hours=1),
    )
    session.commit()

    # published_at is server-set to real wall-clock time at commit; as_of
    # must be at or after that moment for these snapshots to be visible.
    query_as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    scenario = build_scenario(
        session, match_id="match_1", player_a_id="p1", player_b_id="p2", as_of=query_as_of,
        instruments=[(InstrumentType.MONEYLINE, "book_a")],
    )

    assert scenario.player_a_profile_snapshot_id is not None
    assert scenario.player_a_state_snapshot_id is not None
    assert scenario.player_b_profile_snapshot_id is not None
    assert scenario.match_context_snapshot_id is not None
    assert len(scenario.market_references) == 1
    assert scenario.market_references[0].odds == 1.85


def test_build_scenario_missing_data_yields_none_refs_not_errors(session: Session) -> None:
    scenario = build_scenario(
        session, match_id="unknown_match", player_a_id="ghost_a", player_b_id="ghost_b", as_of=T0,
        instruments=[(InstrumentType.MONEYLINE, "book_a")],
    )
    assert scenario.player_a_profile_snapshot_id is None
    assert scenario.market_references == []


def test_build_scenario_respects_as_of_never_picks_future_snapshot(session: Session) -> None:
    ce1_repository.publish_snapshot(
        session, entity_type="PlayerProfile", entity_id="p1", fields=_profile(), config_version_id=CONFIG_VERSION_ID
    )
    session.commit()

    scenario = build_scenario(
        session, match_id="match_1", player_a_id="p1", player_b_id="p2",
        as_of=T0 - timedelta(days=365),  # long before the snapshot was published
        instruments=[],
    )
    assert scenario.player_a_profile_snapshot_id is None
