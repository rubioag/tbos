"""Contract tests: guarantee CE.1's published shape is exactly what CE.2's
Common Model Contract expects a Model's `required_fields` lookup to resolve
against. If these break, every downstream Model breaks silently.
"""

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import ENTITY_SCHEMAS, MarketSnapshot, MatchContext, PlayerProfile, PlayerState

_EXPECTED_ENTITIES = {"PlayerProfile", "PlayerState", "MatchContext", "MarketSnapshot"}


def test_all_four_entities_are_registered() -> None:
    assert set(ENTITY_SCHEMAS) == _EXPECTED_ENTITIES


def test_every_field_in_every_schema_is_a_field_envelope() -> None:
    """No raw/unwrapped field may exist anywhere — this is the single most
    important invariant CE.2 Models rely on (Common Model Contract §2:
    required_fields resolve against CE.1 fields *with* metadata).
    """
    for name, schema in ENTITY_SCHEMAS.items():
        for field_name, field_info in schema.model_fields.items():
            annotation = field_info.annotation
            is_envelope = isinstance(annotation, type) and issubclass(annotation, FieldEnvelope)
            assert is_envelope, f"{name}.{field_name} is not a FieldEnvelope (got {annotation})"


def test_serve_model_required_fields_resolve_against_player_profile() -> None:
    """Mirrors the Serve Model's declared required_fields from the frozen
    spec — if PlayerProfile's schema drifts, this test catches it before
    any Model silently starts abstaining on every match.
    """
    required = {
        "first_serve_pct_by_surface",
        "service_points_won_pct_by_surface",
        "aces_per_match_by_surface",
        "hold_rate_by_surface",
    }
    assert required.issubset(PlayerProfile.model_fields.keys())


def test_matchup_model_required_fields_resolve() -> None:
    required = {"h2h_records", "style_tags"}
    assert required.issubset(PlayerProfile.model_fields.keys())


def test_form_fatigue_model_required_fields_resolve_against_player_state() -> None:
    required = {
        "injury_flags",
        "matches_last_14d",
        "sets_played_last_14d",
        "deviation_from_baseline",
    }
    assert required.issubset(PlayerState.model_fields.keys())


def test_surface_model_required_fields_resolve_against_match_context() -> None:
    required = {"surface", "indoor_outdoor"}
    assert required.issubset(MatchContext.model_fields.keys())


def test_market_snapshot_carries_closing_flag_for_ce6() -> None:
    """CE.6 CLV Tracker depends on this exact field existing and being a
    FieldEnvelope[bool] (spec §E, `is_closing_snapshot`).
    """
    assert "is_closing_snapshot" in MarketSnapshot.model_fields
