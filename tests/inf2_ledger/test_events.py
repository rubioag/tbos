import uuid
from datetime import datetime, timezone

from tbos.inf1_config.taxonomy import ActionType, EdgeSourceCategory, InstrumentType, OutcomeResult
from tbos.inf2_ledger.events import (
    ActionPlanSummary,
    CancellationRecordedPayload,
    CapitalAllocation,
    CLVRecordedPayload,
    CorrectionRecordedPayload,
    DecisionRecordedPayload,
    DominantReason,
    ExecutionRecordedPayload,
    OddsSplit,
    OutcomeRecordedPayload,
    VersionStamp,
)


def test_decision_payload_round_trips() -> None:
    payload = DecisionRecordedPayload(
        action_plan=ActionPlanSummary(action_type=ActionType.BET_NOW, stake=50.0),
        dominant_reason=DominantReason(code="POSITIVE_EV_ROBUST", justification="robust edge"),
        capital_allocation=CapitalAllocation(deployed=50.0, reserved_system_wide=9950.0, reasoning="ok"),
        version_stamp=VersionStamp(
            ce2_engine_version="1.0.0",
            ce3_engine_version="1.0.0",
            ce4_engine_version="1.0.0",
            config_version_id=uuid.uuid4(),
        ),
    )
    restored = DecisionRecordedPayload.model_validate_json(payload.model_dump_json())
    assert restored == payload


def test_execution_payload_round_trips() -> None:
    payload = ExecutionRecordedPayload(
        actual_instrument_type=InstrumentType.MONEYLINE,
        actual_odds_per_split=[OddsSplit(book_id="book_a", odds=1.85, stake_portion=50.0)],
        actual_stake_total=50.0,
        execution_timestamp=datetime.now(timezone.utc),
        execution_quality_slippage=-0.01,
        ce5_engine_version="1.0.0",
    )
    restored = ExecutionRecordedPayload.model_validate_json(payload.model_dump_json())
    assert restored == payload


def test_cancellation_payload_round_trips() -> None:
    payload = CancellationRecordedPayload(
        reason="LIQUIDITY_INSUFFICIENT",
        conditions_unmet=["liquidity < threshold"],
        cancellation_timestamp=datetime.now(timezone.utc),
        ce5_engine_version="1.0.0",
    )
    restored = CancellationRecordedPayload.model_validate_json(payload.model_dump_json())
    assert restored == payload


def test_clv_payload_round_trips() -> None:
    payload = CLVRecordedPayload(
        placed_odds=1.85,
        closing_odds=1.75,
        clv_value=0.032,
        vig_adjustment_method="proportional",
        edge_source_category=EdgeSourceCategory.INFORMATIONAL,
        ce6_engine_version="1.0.0",
    )
    restored = CLVRecordedPayload.model_validate_json(payload.model_dump_json())
    assert restored == payload


def test_outcome_payload_round_trips() -> None:
    payload = OutcomeRecordedPayload(
        result=OutcomeResult.WIN, settled_at=datetime.now(timezone.utc), source="official_result_feed"
    )
    restored = OutcomeRecordedPayload.model_validate_json(payload.model_dump_json())
    assert restored == payload


def test_correction_payload_round_trips() -> None:
    payload = CorrectionRecordedPayload(
        corrects_event_id=uuid.uuid4(), reason="wrong result reported initially", replacement_event_id=uuid.uuid4()
    )
    restored = CorrectionRecordedPayload.model_validate_json(payload.model_dump_json())
    assert restored == payload
