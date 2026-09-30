import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import MatchContext, PlayerProfile, PlayerState
from tbos.ce2_prediction.input_bundle import check_required_fields, load_input_bundle, resolve_field_path
from tbos.inf1_config.taxonomy import (
    BestOf,
    FieldAvailability,
    FieldValidity,
    FreshnessStatus,
    InformationReliability,
    Surface,
)

CONFIG_VERSION_ID = uuid.uuid4()


def _env(value: object, *, stale: bool = False) -> FieldEnvelope:
    from tbos.ce1_data.envelope import FreshnessInfo

    freshness = (
        FreshnessInfo(
            collected_at=datetime.now(timezone.utc) - timedelta(days=30),
            age_seconds=30 * 86400,
            threshold_seconds=60,
            status=FreshnessStatus.STALE,
        )
        if stale
        else None
    )
    return FieldEnvelope(
        value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT, freshness=freshness,
    )


def _profile() -> PlayerProfile:
    return PlayerProfile(
        player_id=_env("p1"), ranking=_env(5),
        first_serve_pct_by_surface=_env({"HARD": 0.62}),
        service_points_won_pct_by_surface=_env({"HARD": 0.71}),
        aces_per_match_by_surface=_env({"HARD": 8.2}),
        hold_rate_by_surface=_env({"HARD": 0.85}),
        return_points_won_pct_by_surface=_env({"HARD": 0.38}),
        break_points_converted_pct_by_surface=_env({"HARD": 0.41}, stale=True),
        style_tags=_env(["baseline"]), career_stage=_env("PEAK"), h2h_records=_env([]),
        elo_rating=_env(1500.0), elo_rating_by_surface=_env({"HARD": 1500.0}),
    )


def _match_context() -> MatchContext:
    return MatchContext(
        match_id=_env("match_1"), tournament_id=_env("t1"), round=_env("QF"),
        surface=_env(Surface.HARD), indoor_outdoor=_env("OUTDOOR"),
        weather_temp_c=_env(24.0), weather_wind_kph=_env(5.0), weather_humidity_pct=_env(40.0),
        altitude_m=_env(50.0), scheduled_start=_env(datetime.now(timezone.utc)), best_of=_env(BestOf.BO3),
    )


def test_load_input_bundle_populates_existing_entities(session: Session) -> None:
    ce1_repository.publish_snapshot(
        session, entity_type="PlayerProfile", entity_id="p1", fields=_profile(), config_version_id=CONFIG_VERSION_ID
    )
    ce1_repository.publish_snapshot(
        session, entity_type="MatchContext", entity_id="match_1", fields=_match_context(),
        config_version_id=CONFIG_VERSION_ID,
    )
    session.commit()

    bundle = load_input_bundle(
        session, match_id="match_1", player_a_id="p1", player_b_id="p2",
        as_of=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    assert bundle.player_a_profile is not None
    assert bundle.player_a_profile.ranking.value == 5
    assert bundle.player_b_profile is None  # never published
    assert bundle.match_context is not None
    assert "player_a_profile" in bundle.snapshot_refs
    assert "player_b_profile" not in bundle.snapshot_refs


def test_load_input_bundle_all_missing_still_returns_valid_bundle(session: Session) -> None:
    bundle = load_input_bundle(
        session, match_id="ghost_match", player_a_id="ghost_a", player_b_id="ghost_b",
        as_of=datetime.now(timezone.utc),
    )
    assert bundle.player_a_profile is None
    assert bundle.match_context is None
    assert bundle.snapshot_refs == {}


def test_resolve_field_path_finds_nested_envelope(session: Session) -> None:
    ce1_repository.publish_snapshot(
        session, entity_type="PlayerProfile", entity_id="p1", fields=_profile(), config_version_id=CONFIG_VERSION_ID
    )
    session.commit()
    bundle = load_input_bundle(
        session, match_id="match_1", player_a_id="p1", player_b_id="p2",
        as_of=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    env = resolve_field_path(bundle, "player_a_profile.first_serve_pct_by_surface")
    assert env is not None
    assert env.value == {"HARD": 0.62}


def test_resolve_field_path_missing_parent_entity_returns_none(session: Session) -> None:
    bundle = load_input_bundle(
        session, match_id="ghost", player_a_id="ghost_a", player_b_id="ghost_b", as_of=datetime.now(timezone.utc)
    )
    assert resolve_field_path(bundle, "player_a_profile.first_serve_pct_by_surface") is None


def test_resolve_field_path_unknown_attribute_returns_none(session: Session) -> None:
    bundle = load_input_bundle(
        session, match_id="ghost", player_a_id="ghost_a", player_b_id="ghost_b", as_of=datetime.now(timezone.utc)
    )
    assert resolve_field_path(bundle, "player_a_profile.nonexistent_field") is None


def test_check_required_fields_all_satisfied(session: Session) -> None:
    ce1_repository.publish_snapshot(
        session, entity_type="PlayerProfile", entity_id="p1", fields=_profile(), config_version_id=CONFIG_VERSION_ID
    )
    session.commit()
    bundle = load_input_bundle(
        session, match_id="match_1", player_a_id="p1", player_b_id="p2",
        as_of=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    ok, missing = check_required_fields(bundle, ["player_a_profile.first_serve_pct_by_surface"])
    assert ok is True
    assert missing == []


def test_check_required_fields_stale_but_present_still_satisfies() -> None:
    """Staleness is an Evidence Quality signal, not an abstention gate on
    its own — a stale field is still usable().
    """
    from tbos.ce2_prediction.input_bundle import ModelInputBundle

    bundle = ModelInputBundle(match_id="m", player_a_id="p1", player_b_id="p2", as_of=datetime.now(timezone.utc), player_a_profile=_profile())
    ok, missing = check_required_fields(bundle, ["player_a_profile.break_points_converted_pct_by_surface"])
    assert ok is True


def test_check_required_fields_reports_all_missing_paths() -> None:
    from tbos.ce2_prediction.input_bundle import ModelInputBundle

    bundle = ModelInputBundle(match_id="m", player_a_id="p1", player_b_id="p2", as_of=datetime.now(timezone.utc))
    ok, missing = check_required_fields(
        bundle, ["player_a_profile.first_serve_pct_by_surface", "player_b_profile.hold_rate_by_surface"]
    )
    assert ok is False
    assert set(missing) == {"player_a_profile.first_serve_pct_by_surface", "player_b_profile.hold_rate_by_surface"}
