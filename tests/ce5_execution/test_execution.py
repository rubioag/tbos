import uuid
from datetime import datetime, timezone

import pytest

from tbos.ce4_decision.bias import BiasChecklistResult
from tbos.ce4_decision.capital import CapitalAllocation
from tbos.ce4_decision.decision import DominantReason
from tbos.ce4_decision.ruin_risk import RuinRiskResult
from tbos.ce4_decision.schemas import ActionPlan
from tbos.ce4_decision.stake import StakeResult
from tbos.ce5_execution.execution import NotABetNowPlan, execute_action_plan
from tbos.ce5_execution.optimizer import BookQuote
from tbos.ce5_execution.schemas import CancellationRecord, ExecutionRecord
from tbos.inf1_config.taxonomy import ActionType, CancellationReason, InstrumentType

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _plan(*, action_type: ActionType = ActionType.BET_NOW, stake_amount: float = 100.0) -> ActionPlan:
    return ActionPlan(
        action_plan_id=uuid.uuid4(), edge_id=uuid.uuid4(), match_id="match_1",
        instrument_type=InstrumentType.MONEYLINE, book_id="book_a", action_type=action_type,
        stake_result=StakeResult(raw_kelly_fraction=0.1, adjusted_fraction=0.02, stake_amount=stake_amount),
        capital_allocation=CapitalAllocation(deployed=stake_amount, reserved_system_wide=9900, reasoning="ok", capped=False),
        dominant_reason=DominantReason(code="POSITIVE_EV_ROBUST", justification="x"),
        bias_checklist_result=BiasChecklistResult(passed=True, flags=[]),
        ruin_risk_result=RuinRiskResult(ruin_probability=0.001, passed=True, simulated_paths=100),
        ce4_engine_version="1.0.0", computed_at=NOW,
    )


def test_execution_preserves_instrument_type_from_plan() -> None:
    plan = _plan()
    quotes = [BookQuote(book_id="book_a", odds=1.9, available_liquidity=1000)]
    record = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)
    assert isinstance(record, ExecutionRecord)
    assert record.instrument_type == plan.instrument_type


def test_execution_never_exceeds_target_stake() -> None:
    plan = _plan(stake_amount=100.0)
    quotes = [BookQuote(book_id="book_a", odds=1.9, available_liquidity=10_000)]
    record = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)
    assert record.actual_stake_total <= record.target_stake


def test_slippage_computed_against_target_odds_only() -> None:
    plan = _plan(stake_amount=100.0)
    quotes = [BookQuote(book_id="book_a", odds=1.8, available_liquidity=1000)]
    record = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)
    assert record.execution_quality_slippage == pytest.approx(1.8 - 1.9)


def test_insufficient_liquidity_cancels_instead_of_partial_execution() -> None:
    plan = _plan(stake_amount=100.0)
    quotes = [BookQuote(book_id="book_a", odds=1.9, available_liquidity=10)]  # far below min_fill_fraction
    result = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)
    assert isinstance(result, CancellationRecord)
    assert result.reason == CancellationReason.LIQUIDITY_INSUFFICIENT


def test_partial_fill_above_min_fraction_still_executes() -> None:
    plan = _plan(stake_amount=100.0)
    quotes = [BookQuote(book_id="book_a", odds=1.9, available_liquidity=60)]  # 60% >= default 50% min fill
    result = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)
    assert isinstance(result, ExecutionRecord)
    assert result.actual_stake_total == 60


def test_defer_plan_cannot_be_executed() -> None:
    plan = _plan(action_type=ActionType.DEFER)
    with pytest.raises(NotABetNowPlan):
        execute_action_plan(plan, target_odds=1.9, quotes=[], as_of=NOW)


def test_pass_plan_cannot_be_executed() -> None:
    plan = _plan(action_type=ActionType.PASS)
    with pytest.raises(NotABetNowPlan):
        execute_action_plan(plan, target_odds=1.9, quotes=[], as_of=NOW)


def test_split_execution_average_odds_is_weighted() -> None:
    plan = _plan(stake_amount=100.0)
    quotes = [
        BookQuote(book_id="a", odds=2.0, available_liquidity=50),
        BookQuote(book_id="b", odds=1.8, available_liquidity=50),
    ]
    record = execute_action_plan(plan, target_odds=1.9, quotes=quotes, as_of=NOW)
    assert record.average_odds == pytest.approx((2.0 * 50 + 1.8 * 50) / 100)
