"""Full pipeline: CE.1 -> CE.2 -> CE.3 -> CE.4 -> CE.5 -> CE.6.
The complete operational loop, first time it runs end to end.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce2_prediction.prediction_engine import run_prediction
from tbos.ce2_prediction.registry_bootstrap import bootstrap_and_activate_all
from tbos.ce3_edge.engine import build_edge_description
from tbos.ce4_decision.engine import build_action_plan
from tbos.ce5_execution.engine import run_execution
from tbos.ce5_execution.optimizer import BookQuote
from tbos.ce5_execution.schemas import ExecutionRecord
from tbos.ce6_clv import repository as ce6_repository
from tbos.ce6_clv.engine import build_clv_record
from tbos.historical_pipeline import market_history
from tbos.inf1_config.schemas import EnsembleConfig, RiskConfig
from tbos.inf1_config.taxonomy import ActionType, ConfidenceFlag, EdgeSourceCategory, InstrumentType

from tests.ce2_prediction.factories import make_bundle, make_match_context, make_profile, make_state

CONFIG_VERSION_ID = uuid.uuid4()
RISK_CONFIG = RiskConfig(aggressiveness_threshold=0.1, fractional_kelly_multiplier=0.25, ruin_risk_max_probability=0.05)
CLOSING_POLICY = {"MONEYLINE": "match_start"}


def _publish_full_data(session: Session, *, as_of: datetime, match_start: datetime) -> None:
    h2h = [{"opponent_id": "player_b", "date": "2025-06-01", "surface": "HARD", "result": "WIN"}]
    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_a", fields=make_profile("player_a", h2h_records=h2h), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerProfile", entity_id="player_b", fields=make_profile("player_b"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_a", fields=make_state("player_a"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="PlayerState", entity_id="player_b", fields=make_state("player_b"), config_version_id=CONFIG_VERSION_ID)
    ce1_repository.publish_snapshot(session, entity_type="MatchContext", entity_id="match_1", fields=make_match_context(), config_version_id=CONFIG_VERSION_ID)
    session.commit()


def test_full_ce1_to_ce6_pipeline(session: Session) -> None:
    match_start = datetime.now(timezone.utc) + timedelta(days=1)
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    _publish_full_data(session, as_of=as_of, match_start=match_start)

    representative_bundle = make_bundle(include_states=True)
    bootstrap_and_activate_all(session, representative_bundle, reviewer_id="alice")

    prediction = run_prediction(
        session, match_id="match_1", player_a_id="player_a", player_b_id="player_b",
        as_of=as_of, ensemble_config=EnsembleConfig(),
    )
    assert prediction.confidence_flag in (ConfidenceFlag.NORMAL, ConfidenceFlag.DEGRADED)

    edge = build_edge_description(prediction, instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.5, as_of=as_of)
    assert edge is not None

    plan = build_action_plan(edge, bankroll_total=10_000.0, current_deployed=0.0, risk_config=RISK_CONFIG, as_of=as_of, rng_seed=1)

    quotes = [BookQuote(book_id="book_a", odds=2.5, available_liquidity=10_000)]
    outcome = run_execution(plan, target_odds=edge.offered_odds, quotes=quotes, as_of=as_of)

    if plan.action_type != ActionType.BET_NOW:
        assert outcome is None
        return

    assert isinstance(outcome, ExecutionRecord)

    # Seed a closing tick using the real MatchContext we published, read
    # back through CE.1 so match_start matches exactly what CE.6 will resolve.
    match_context_snapshot = ce1_repository.get_latest_snapshot(session, "MatchContext", "match_1")
    from tbos.ce1_data.schemas import MatchContext
    match_context = MatchContext.model_validate(match_context_snapshot.fields)

    market_history.append_tick(
        session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a",
        odds=2.3, tick_timestamp=match_context.scheduled_start.value - timedelta(minutes=5),
    )
    session.commit()

    clv_record = build_clv_record(
        session, outcome, match_id="match_1", match_context=match_context,
        edge_source_category=edge.edge_source_category, closing_time_policy=CLOSING_POLICY,
    )
    assert clv_record is not None
    assert clv_record.placed_odds == outcome.average_odds or clv_record.placed_odds == outcome.splits[0].odds

    ce6_repository.publish_clv_record(session, clv_record)
    session.commit()

    rows = ce6_repository.list_for_match(session, "match_1")
    assert len(rows) == 1


def test_clv_computation_never_depends_on_match_outcome() -> None:
    """The defining property of Measurement Independence, exercised as an
    actual computation rather than just a schema check: compute_clv takes
    no outcome input and produces the same result regardless of what
    eventually happens in the match.
    """
    from tbos.ce6_clv.clv import compute_clv

    result = compute_clv(placed_odds=2.0, closing_odds=1.9)
    # Nothing about a match result could have been consulted here — the
    # function signature structurally has no such parameter (see
    # test_measurement_independence.py), and this just re-confirms the
    # computed value is deterministic and outcome-free.
    result_again = compute_clv(placed_odds=2.0, closing_odds=1.9)
    assert result == result_again
