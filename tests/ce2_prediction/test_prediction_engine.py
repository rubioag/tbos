"""CE.2.9 end-to-end integration test — the first time in this project
that CE.1 snapshot -> 5 Models -> Ensemble -> Uncertainty -> Evidence
Quality -> Abstention Policy runs as one real pipeline.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce2_prediction.prediction_engine import run_prediction
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.inf1_config.schemas import EnsembleConfig
from tbos.inf1_config.taxonomy import ConfidenceFlag

from tests.ce2_prediction.factories import make_bundle, make_match_context, make_profile, make_state

CONFIG_VERSION_ID = uuid.uuid4()


def _publish_full_data(session: Session, *, as_of: datetime) -> None:
    h2h = [{"opponent_id": "player_b", "date": "2025-06-01", "surface": "HARD", "result": "WIN"}]
    profile_a = make_profile("player_a", h2h_records=h2h)
    profile_b = make_profile("player_b")
    state_a = make_state("player_a")
    state_b = make_state("player_b")
    context = make_match_context()

    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_a", fields=profile_a, config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_b", fields=profile_b, config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_a", fields=state_a, config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_b", fields=state_b, config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="MatchContext", entity_id="match_1", fields=context, config_version_id=CONFIG_VERSION_ID)
    session.commit()


def test_full_pipeline_end_to_end_produces_publishable_prediction(session: Session) -> None:
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    _publish_full_data(session, as_of=as_of)

    representative_bundle = make_bundle(include_states=True)
    activated = bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")
    assert len(activated) == 5  # all 5 base Models pass the battery, per CE.2.8

    result = run_prediction(
        session, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )

    assert result.confidence_flag in (ConfidenceFlag.NORMAL, ConfidenceFlag.DEGRADED)
    assert result.probability_player_a is not None
    assert 0.0 < result.probability_player_a < 1.0
    assert result.uncertainty is not None
    assert result.evidence_quality is not None
    assert len(result.participating_models) >= 3


def test_no_active_models_yields_abstained(session: Session) -> None:
    """No bootstrap step run — the registry is empty, so nothing can vote."""
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    _publish_full_data(session, as_of=as_of)

    result = run_prediction(
        session, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )
    assert result.confidence_flag == ConfidenceFlag.ABSTAINED
    assert result.probability_player_a is None


def test_no_published_data_yields_abstained_even_with_active_models(session: Session) -> None:
    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    result = run_prediction(
        session, match_id="ghost_match", player_a_id="ghost_a", player_b_id="ghost_b",
        as_of=datetime.now(timezone.utc), ensemble_config=EnsembleConfig(),
    )
    assert result.confidence_flag == ConfidenceFlag.ABSTAINED


def test_strict_quorum_config_forces_abstention_even_with_full_data(session: Session) -> None:
    """Proves the Abstention Policy's thresholds are genuinely
    config-driven — Configuration Independence Principle exercised
    end-to-end, not just at the unit level.
    """
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    _publish_full_data(session, as_of=as_of)
    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    impossible_quorum_config = EnsembleConfig(quorum_minimum_absolute=99)

    result = run_prediction(
        session, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=impossible_quorum_config,
    )
    assert result.confidence_flag == ConfidenceFlag.ABSTAINED
    assert "quorum_below_absolute_minimum" in result.triggered_abstention_rules
