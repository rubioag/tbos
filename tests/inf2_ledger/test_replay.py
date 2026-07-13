import uuid
from datetime import datetime, timezone

import pytest

from tbos.inf1_config.taxonomy import (
    ActionType,
    BetStatus,
    EdgeSourceCategory,
    EventType,
    InstrumentType,
    OutcomeResult,
)
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
from tbos.inf2_ledger.models import Event
from tbos.inf2_ledger.replay import EmptyEventStream, compute_bankroll_state, replay_bet

BET_ID = uuid.uuid4()
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _row(event_type: EventType, payload, *, seq: int) -> Event:
    """Construct an in-memory Event row without touching the DB — replay_bet
    only depends on ordering (id) and the decoded fields.
    """
    return Event(
        id=seq,
        event_id=uuid.uuid4(),
        bet_id=BET_ID,
        event_type=event_type.value,
        payload=payload.model_dump(mode="json"),
        timestamp=NOW,
    )


def _decision() -> DecisionRecordedPayload:
    return DecisionRecordedPayload(
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


def _execution(stake: float = 50.0, odds: float = 2.0) -> ExecutionRecordedPayload:
    return ExecutionRecordedPayload(
        actual_instrument_type=InstrumentType.MONEYLINE,
        actual_odds_per_split=[OddsSplit(book_id="book_a", odds=odds, stake_portion=stake)],
        actual_stake_total=stake,
        execution_timestamp=NOW,
        execution_quality_slippage=0.0,
        ce5_engine_version="1.0.0",
    )


def _outcome(result: OutcomeResult) -> OutcomeRecordedPayload:
    return OutcomeRecordedPayload(result=result, settled_at=NOW, source="test")


def test_replay_empty_stream_raises() -> None:
    with pytest.raises(EmptyEventStream):
        replay_bet([])


def test_replay_decision_only_is_decided() -> None:
    events = [_row(EventType.DECISION_RECORDED, _decision(), seq=1)]
    record = replay_bet(events)
    assert record.status == BetStatus.DECIDED
    assert record.decision is not None
    assert record.event_count == 1


def test_replay_decision_then_execution_is_awaiting_settlement() -> None:
    events = [
        _row(EventType.DECISION_RECORDED, _decision(), seq=1),
        _row(EventType.EXECUTION_RECORDED, _execution(), seq=2),
    ]
    record = replay_bet(events)
    assert record.status == BetStatus.AWAITING_SETTLEMENT
    assert record.execution is not None


def test_replay_decision_then_cancellation_is_cancelled() -> None:
    cancellation = CancellationRecordedPayload(
        reason="PRECONDITION_TIMEOUT", cancellation_timestamp=NOW, ce5_engine_version="1.0.0"
    )
    events = [
        _row(EventType.DECISION_RECORDED, _decision(), seq=1),
        _row(EventType.CANCELLATION_RECORDED, cancellation, seq=2),
    ]
    record = replay_bet(events)
    assert record.status == BetStatus.CANCELLED


def test_replay_full_chain_win_is_settled() -> None:
    clv = CLVRecordedPayload(
        placed_odds=2.0,
        closing_odds=1.9,
        clv_value=0.05,
        vig_adjustment_method="proportional",
        edge_source_category=EdgeSourceCategory.MODEL,
        ce6_engine_version="1.0.0",
    )
    events = [
        _row(EventType.DECISION_RECORDED, _decision(), seq=1),
        _row(EventType.EXECUTION_RECORDED, _execution(), seq=2),
        _row(EventType.CLV_RECORDED, clv, seq=3),
        _row(EventType.OUTCOME_RECORDED, _outcome(OutcomeResult.WIN), seq=4),
    ]
    record = replay_bet(events)
    assert record.status == BetStatus.SETTLED
    assert record.outcome.result == OutcomeResult.WIN
    assert record.clv is not None
    assert record.event_count == 4


def test_replay_execution_after_cancellation_clears_cancellation() -> None:
    """Edge case: a monitored ActionPlan that first looked cancellable but
    then executed on a later precondition check must not be reported as
    both cancelled and executed — execution wins.
    """
    cancellation = CancellationRecordedPayload(
        reason="PRECONDITION_TIMEOUT", cancellation_timestamp=NOW, ce5_engine_version="1.0.0"
    )
    events = [
        _row(EventType.DECISION_RECORDED, _decision(), seq=1),
        _row(EventType.CANCELLATION_RECORDED, cancellation, seq=2),
        _row(EventType.EXECUTION_RECORDED, _execution(), seq=3),
    ]
    record = replay_bet(events)
    assert record.status == BetStatus.AWAITING_SETTLEMENT
    assert record.cancellation is None


def test_replay_correction_never_mutates_original_event_only_appends() -> None:
    """CORRECTION_RECORDED marks that OUTCOME_RECORDED#1 (LOSS) was wrong;
    a fresh OUTCOME_RECORDED#2 (WIN) is what the replay actually reflects.
    Both original events remain intact in the raw event list.
    """
    loss_row = _row(EventType.OUTCOME_RECORDED, _outcome(OutcomeResult.LOSS), seq=4)
    win_row = _row(EventType.OUTCOME_RECORDED, _outcome(OutcomeResult.WIN), seq=6)
    correction = CorrectionRecordedPayload(
        corrects_event_id=loss_row.event_id, reason="scoring error in feed", replacement_event_id=win_row.event_id
    )

    events = [
        _row(EventType.DECISION_RECORDED, _decision(), seq=1),
        _row(EventType.EXECUTION_RECORDED, _execution(), seq=2),
        loss_row,
        _row(EventType.CORRECTION_RECORDED, correction, seq=5),
        win_row,
    ]
    record = replay_bet(events)

    assert record.outcome.result == OutcomeResult.WIN  # latest wins
    assert len(record.corrections) == 1
    assert record.corrections[0].corrects_event_id == loss_row.event_id
    assert record.corrections[0].replacement_event_id == win_row.event_id
    # the original LOSS event is untouched in the raw stream itself:
    assert loss_row.payload["result"] == "LOSS"


def test_bankroll_state_deployed_only_for_awaiting_settlement() -> None:
    events = [
        _row(EventType.DECISION_RECORDED, _decision(), seq=1),
        _row(EventType.EXECUTION_RECORDED, _execution(stake=50.0), seq=2),
    ]
    record = replay_bet(events)
    state = compute_bankroll_state([record], total_capital=10_000.0)
    assert state.deployed == 50.0
    assert state.settled_pnl == 0.0
    assert state.current_balance == 10_000.0


def test_bankroll_state_settled_win_adds_profit() -> None:
    events = [
        _row(EventType.DECISION_RECORDED, _decision(), seq=1),
        _row(EventType.EXECUTION_RECORDED, _execution(stake=50.0, odds=2.0), seq=2),
        _row(EventType.OUTCOME_RECORDED, _outcome(OutcomeResult.WIN), seq=3),
    ]
    record = replay_bet(events)
    state = compute_bankroll_state([record], total_capital=10_000.0)
    assert state.deployed == 0.0  # no longer AWAITING_SETTLEMENT once SETTLED
    assert state.settled_pnl == 50.0  # stake * (odds - 1) = 50 * 1.0
    assert state.current_balance == 10_050.0


def test_bankroll_state_settled_loss_subtracts_stake() -> None:
    events = [
        _row(EventType.DECISION_RECORDED, _decision(), seq=1),
        _row(EventType.EXECUTION_RECORDED, _execution(stake=50.0, odds=2.0), seq=2),
        _row(EventType.OUTCOME_RECORDED, _outcome(OutcomeResult.LOSS), seq=3),
    ]
    record = replay_bet(events)
    state = compute_bankroll_state([record], total_capital=10_000.0)
    assert state.settled_pnl == -50.0
    assert state.current_balance == 9_950.0


def test_bankroll_state_void_has_no_pnl_impact() -> None:
    events = [
        _row(EventType.DECISION_RECORDED, _decision(), seq=1),
        _row(EventType.EXECUTION_RECORDED, _execution(stake=50.0, odds=2.0), seq=2),
        _row(EventType.OUTCOME_RECORDED, _outcome(OutcomeResult.VOID), seq=3),
    ]
    record = replay_bet(events)
    state = compute_bankroll_state([record], total_capital=10_000.0)
    assert state.settled_pnl == 0.0
    assert state.current_balance == 10_000.0
