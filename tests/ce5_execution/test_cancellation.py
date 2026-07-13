import uuid
from datetime import datetime, timezone

from tbos.ce5_execution.cancellation import (
    liquidity_insufficient_cancellation,
    precondition_timeout_cancellation,
)
from tbos.inf1_config.taxonomy import CancellationReason

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
PLAN_ID = uuid.uuid4()


def test_liquidity_insufficient_reason_and_conditions() -> None:
    record = liquidity_insufficient_cancellation(PLAN_ID, target_stake=100.0, filled_stake=20.0, as_of=NOW)
    assert record.reason == CancellationReason.LIQUIDITY_INSUFFICIENT
    assert "20.00" in record.conditions_unmet[0]
    assert "100.00" in record.conditions_unmet[0]


def test_precondition_timeout_reason() -> None:
    record = precondition_timeout_cancellation(PLAN_ID, as_of=NOW)
    assert record.reason == CancellationReason.PRECONDITION_TIMEOUT


def test_cancellation_always_references_the_original_plan() -> None:
    record = liquidity_insufficient_cancellation(PLAN_ID, target_stake=100.0, filled_stake=0.0, as_of=NOW)
    assert record.action_plan_id == PLAN_ID
