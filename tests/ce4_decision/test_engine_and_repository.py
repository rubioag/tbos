from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tbos.ce3_edge.engine import build_edge_description
from tbos.ce2_prediction.prediction_engine import PredictionOutput
from tbos.ce4_decision import repository
from tbos.ce4_decision.engine import build_action_plan
from tbos.inf1_config.schemas import RiskConfig
from tbos.inf1_config.taxonomy import ActionType, ConfidenceFlag, InstrumentType

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
RISK_CONFIG = RiskConfig(aggressiveness_threshold=0.2)


def _prediction(probability: float = 0.6, uncertainty: float = 0.1) -> PredictionOutput:
    return PredictionOutput(
        match_id="match_1", confidence_flag=ConfidenceFlag.NORMAL, probability_player_a=probability,
        log_odds=0.4, uncertainty=uncertainty, evidence_quality=0.7, participating_models=["serve_model"],
        abstained_models=[], triggered_abstention_rules=[], ensemble_version="1.0.0",
    )


def test_build_action_plan_produces_bet_now_for_strong_edge() -> None:
    edge = build_edge_description(_prediction(), instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.2, as_of=NOW)
    plan = build_action_plan(edge, bankroll_total=10_000, current_deployed=0, risk_config=RISK_CONFIG, as_of=NOW, rng_seed=1)
    assert plan.action_type == ActionType.BET_NOW
    assert plan.stake_result.stake_amount > 0
    assert plan.capital_allocation.deployed == plan.stake_result.stake_amount


def test_non_bet_now_action_deploys_zero_capital() -> None:
    edge = build_edge_description(_prediction(probability=0.4), instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=1.5, as_of=NOW)
    plan = build_action_plan(edge, bankroll_total=10_000, current_deployed=0, risk_config=RISK_CONFIG, as_of=NOW, rng_seed=1)
    assert plan.action_type == ActionType.PASS
    assert plan.capital_allocation.deployed == 0.0


def test_publish_and_retrieve_action_plan(session: Session) -> None:
    edge = build_edge_description(_prediction(), instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.2, as_of=NOW)
    plan = build_action_plan(edge, bankroll_total=10_000, current_deployed=0, risk_config=RISK_CONFIG, as_of=NOW, rng_seed=1)
    repository.publish_action_plan(session, plan)
    session.commit()

    fetched = repository.get_action_plan(session, plan.action_plan_id)
    assert fetched is not None
    assert fetched.action_type == plan.action_type.value


def test_list_for_match(session: Session) -> None:
    edge = build_edge_description(_prediction(), instrument_type=InstrumentType.MONEYLINE, book_id="book_a", offered_odds=2.2, as_of=NOW)
    plan = build_action_plan(edge, bankroll_total=10_000, current_deployed=0, risk_config=RISK_CONFIG, as_of=NOW, rng_seed=1)
    repository.publish_action_plan(session, plan)
    session.commit()

    rows = repository.list_for_match(session, "match_1")
    assert len(rows) == 1
