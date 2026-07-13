"""Full pipeline: CE.1 snapshots -> CE.2 prediction -> CE.3 edge
description -> CE.4 action plan.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce2_prediction.prediction_engine import run_prediction
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.ce3_edge.engine import build_edge_description
from tbos.ce4_decision import repository as ce4_repository
from tbos.ce4_decision.engine import build_action_plan
from tbos.inf1_config.schemas import EnsembleConfig, RiskConfig
from tbos.inf1_config.taxonomy import ActionType, ConfidenceFlag, InstrumentType

from tests.ce2_prediction.factories import make_bundle, make_match_context, make_profile, make_state

CONFIG_VERSION_ID = uuid.uuid4()
RISK_CONFIG = RiskConfig(aggressiveness_threshold=0.1, fractional_kelly_multiplier=0.25, ruin_risk_max_probability=0.05)


def _publish_full_data(session: Session, *, as_of: datetime) -> None:
    h2h = [{"opponent_id": "player_b", "date": "2025-06-01", "surface": "HARD", "result": "WIN"}]
    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_a", fields=make_profile("player_a", h2h_records=h2h), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_b", fields=make_profile("player_b"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_a", fields=make_state("player_a"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_b", fields=make_state("player_b"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="MatchContext", entity_id="match_1", fields=make_match_context(), config_version_id=CONFIG_VERSION_ID)
    session.commit()


def test_full_ce1_to_ce4_pipeline(session: Session) -> None:
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    _publish_full_data(session, as_of=as_of)

    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    prediction = run_prediction(
        session, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )
    assert prediction.confidence_flag in (ConfidenceFlag.NORMAL, ConfidenceFlag.DEGRADED)

    edge = build_edge_description(
        prediction, instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.5, as_of=as_of,
    )
    assert edge is not None

    plan = build_action_plan(
        edge, bankroll_total=10_000.0, current_deployed=0.0, risk_config=RISK_CONFIG, as_of=as_of, rng_seed=1,
    )
    assert plan.action_type in (ActionType.BET_NOW, ActionType.DEFER, ActionType.PASS)
    assert plan.dominant_reason.justification

    ce4_repository.publish_action_plan(session, plan)
    session.commit()

    rows = ce4_repository.list_for_match(session, "match_1")
    assert len(rows) == 1


def test_decision_never_alters_ev_or_probability_from_ce3() -> None:
    """Decision Neutrality boundary: CE.4 reads CE.3's numbers, never
    mutates them, regardless of what action it selects.
    """
    from tests.ce4_decision.test_engine_and_repository import _prediction

    edge = build_edge_description(_prediction(), instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.2, as_of=datetime.now(timezone.utc))
    original_ev = edge.ev_distribution.expected
    original_probability = edge.probability_used

    build_action_plan(edge, bankroll_total=10_000, current_deployed=0, risk_config=RISK_CONFIG, as_of=datetime.now(timezone.utc), rng_seed=1)

    assert edge.ev_distribution.expected == original_ev
    assert edge.probability_used == original_probability
