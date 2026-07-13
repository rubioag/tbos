"""Full pipeline: CE.1 -> CE.2 -> CE.3 -> CE.4 -> CE.5."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce2_prediction.prediction_engine import run_prediction
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.ce3_edge.engine import build_edge_description
from tbos.ce4_decision.engine import build_action_plan
from tbos.ce5_execution import repository as ce5_repository
from tbos.ce5_execution.engine import run_execution
from tbos.ce5_execution.optimizer import BookQuote
from tbos.ce5_execution.schemas import CancellationRecord, ExecutionRecord
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


def test_full_ce1_to_ce5_pipeline(session: Session) -> None:
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

    plan = build_action_plan(edge, bankroll_total=10_000.0, current_deployed=0.0, risk_config=RISK_CONFIG, as_of=as_of, rng_seed=1)

    quotes = [BookQuote(book_id="book_a", odds=2.5, available_liquidity=10_000)]
    outcome = run_execution(plan, target_odds=edge.offered_odds, quotes=quotes, as_of=as_of)

    if plan.action_type == ActionType.BET_NOW:
        assert isinstance(outcome, (ExecutionRecord, CancellationRecord))
        ce5_repository.publish_outcome(session, outcome)
        session.commit()
        rows = ce5_repository.get_outcomes_for_plan(session, plan.action_plan_id)
        assert len(rows) == 1
    else:
        assert outcome is None


def test_defer_and_pass_plans_never_reach_execution(session: Session) -> None:
    """A DEFER/PASS ActionPlan must produce no execution outcome at all —
    not even an attempted one."""
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    _publish_full_data(session, as_of=as_of)
    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    prediction = run_prediction(
        session, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )
    # Deliberately bad odds -> negative EV -> PASS
    edge = build_edge_description(prediction, instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=1.01, as_of=as_of)
    assert edge is not None
    plan = build_action_plan(edge, bankroll_total=10_000.0, current_deployed=0.0, risk_config=RISK_CONFIG, as_of=as_of, rng_seed=1)
    assert plan.action_type == ActionType.PASS

    outcome = run_execution(plan, target_odds=edge.offered_odds, quotes=[], as_of=as_of)
    assert outcome is None
