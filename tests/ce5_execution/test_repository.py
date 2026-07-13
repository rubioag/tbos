import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tbos.ce4_decision.bias import BiasChecklistResult
from tbos.ce4_decision.capital import CapitalAllocation
from tbos.ce4_decision.decision import DominantReason
from tbos.ce4_decision.ruin_risk import RuinRiskResult
from tbos.ce4_decision.schemas import ActionPlan
from tbos.ce4_decision.stake import StakeResult
from tbos.ce5_execution import repository
from tbos.ce5_execution.execution import execute_action_plan
from tbos.ce5_execution.optimizer import BookQuote
from tbos.inf1_config.taxonomy import ActionType, InstrumentType

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _plan() -> ActionPlan:
    return ActionPlan(
        action_plan_id=uuid.uuid4(), edge_id=uuid.uuid4(), match_id="match_1",
        instrument_type=InstrumentType.MONEYLINE, book_id="book_a", action_type=ActionType.BET_NOW,
        stake_result=StakeResult(raw_kelly_fraction=0.1, adjusted_fraction=0.02, stake_amount=100.0),
        capital_allocation=CapitalAllocation(deployed=100.0, reserved_system_wide=9900, reasoning="ok", capped=False),
        dominant_reason=DominantReason(code="POSITIVE_EV_ROBUST", justification="x"),
        bias_checklist_result=BiasChecklistResult(passed=True, flags=[]),
        ruin_risk_result=RuinRiskResult(ruin_probability=0.001, passed=True, simulated_paths=100),
        ce4_engine_version="1.0.0", computed_at=NOW,
    )


def test_publish_and_retrieve_execution_outcome(session: Session) -> None:
    plan = _plan()
    quotes = [BookQuote(book_id="book_a", odds=1.9, available_liquidity=1000)]
    record = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)

    repository.publish_outcome(session, record)
    session.commit()

    rows = repository.get_outcomes_for_plan(session, plan.action_plan_id)
    assert len(rows) == 1
    assert rows[0].outcome_type == "EXECUTED"


def test_publish_cancellation_outcome(session: Session) -> None:
    plan = _plan()
    quotes = [BookQuote(book_id="book_a", odds=1.9, available_liquidity=5)]
    record = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)

    repository.publish_outcome(session, record)
    session.commit()

    rows = repository.get_outcomes_for_plan(session, plan.action_plan_id)
    assert rows[0].outcome_type == "CANCELLED"
