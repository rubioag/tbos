import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from tbos.common import ImmutableRecordError
from tbos.inf1_config.taxonomy import ActionType, EventType, OutcomeResult
from tbos.inf2_ledger import repository
from tbos.inf2_ledger.events import (
    ActionPlanSummary,
    CapitalAllocation,
    DecisionRecordedPayload,
    DominantReason,
    ExecutionRecordedPayload,
    OddsSplit,
    OutcomeRecordedPayload,
    VersionStamp,
)
from tbos.inf1_config.taxonomy import InstrumentType


def _decision_payload(stake: float = 50.0) -> DecisionRecordedPayload:
    return DecisionRecordedPayload(
        action_plan=ActionPlanSummary(action_type=ActionType.BET_NOW, stake=stake),
        dominant_reason=DominantReason(code="POSITIVE_EV_ROBUST", justification="robust edge"),
        capital_allocation=CapitalAllocation(deployed=stake, reserved_system_wide=9950.0, reasoning="ok"),
        version_stamp=VersionStamp(
            ce2_engine_version="1.0.0",
            ce3_engine_version="1.0.0",
            ce4_engine_version="1.0.0",
            config_version_id=uuid.uuid4(),
        ),
    )


def _execution_payload(stake: float = 50.0, odds: float = 2.0) -> ExecutionRecordedPayload:
    return ExecutionRecordedPayload(
        actual_instrument_type=InstrumentType.MONEYLINE,
        actual_odds_per_split=[OddsSplit(book_id="book_a", odds=odds, stake_portion=stake)],
        actual_stake_total=stake,
        execution_timestamp=datetime.now(timezone.utc),
        execution_quality_slippage=0.0,
        ce5_engine_version="1.0.0",
    )


def test_append_and_read_events_for_bet_in_order(session: Session) -> None:
    bet_id = uuid.uuid4()
    repository.append_event(
        session, bet_id=bet_id, event_type=EventType.DECISION_RECORDED, payload=_decision_payload()
    )
    repository.append_event(
        session, bet_id=bet_id, event_type=EventType.EXECUTION_RECORDED, payload=_execution_payload()
    )
    session.commit()

    events = repository.get_events_for_bet(session, bet_id)
    assert [e.event_type for e in events] == ["DECISION_RECORDED", "EXECUTION_RECORDED"]
    assert events[0].id < events[1].id


def test_event_is_immutable(session: Session) -> None:
    bet_id = uuid.uuid4()
    row = repository.append_event(
        session, bet_id=bet_id, event_type=EventType.DECISION_RECORDED, payload=_decision_payload()
    )
    session.commit()

    row.event_type = "TAMPERED"
    with pytest.raises(ImmutableRecordError):
        session.commit()


def test_get_bet_record_replays_correctly(session: Session) -> None:
    bet_id = uuid.uuid4()
    repository.append_event(
        session, bet_id=bet_id, event_type=EventType.DECISION_RECORDED, payload=_decision_payload()
    )
    repository.append_event(
        session, bet_id=bet_id, event_type=EventType.EXECUTION_RECORDED, payload=_execution_payload()
    )
    repository.append_event(
        session,
        bet_id=bet_id,
        event_type=EventType.OUTCOME_RECORDED,
        payload=OutcomeRecordedPayload(result=OutcomeResult.WIN, settled_at=datetime.now(timezone.utc), source="t"),
    )
    session.commit()

    record = repository.get_bet_record(session, bet_id)
    assert record is not None
    assert record.status.value == "SETTLED"
    assert record.event_count == 3


def test_get_bet_record_returns_none_for_unknown_bet(session: Session) -> None:
    assert repository.get_bet_record(session, uuid.uuid4()) is None


def test_timeline_is_global_and_ordered_across_bets(session: Session) -> None:
    bet_a, bet_b = uuid.uuid4(), uuid.uuid4()
    repository.append_event(
        session, bet_id=bet_a, event_type=EventType.DECISION_RECORDED, payload=_decision_payload()
    )
    repository.append_event(
        session, bet_id=bet_b, event_type=EventType.DECISION_RECORDED, payload=_decision_payload()
    )
    repository.append_event(
        session, bet_id=bet_a, event_type=EventType.EXECUTION_RECORDED, payload=_execution_payload()
    )
    session.commit()

    timeline = repository.get_timeline(session)
    assert [e.bet_id for e in timeline] == [bet_a, bet_b, bet_a]
    assert [e.id for e in timeline] == sorted(e.id for e in timeline)


def test_list_bet_ids_returns_distinct(session: Session) -> None:
    bet_id = uuid.uuid4()
    repository.append_event(
        session, bet_id=bet_id, event_type=EventType.DECISION_RECORDED, payload=_decision_payload()
    )
    repository.append_event(
        session, bet_id=bet_id, event_type=EventType.EXECUTION_RECORDED, payload=_execution_payload()
    )
    session.commit()

    assert repository.list_bet_ids(session) == [bet_id]


def test_bankroll_state_across_multiple_bets(session: Session) -> None:
    settled_bet, open_bet = uuid.uuid4(), uuid.uuid4()

    repository.append_event(
        session, bet_id=settled_bet, event_type=EventType.DECISION_RECORDED, payload=_decision_payload(100.0)
    )
    repository.append_event(
        session,
        bet_id=settled_bet,
        event_type=EventType.EXECUTION_RECORDED,
        payload=_execution_payload(stake=100.0, odds=2.0),
    )
    repository.append_event(
        session,
        bet_id=settled_bet,
        event_type=EventType.OUTCOME_RECORDED,
        payload=OutcomeRecordedPayload(result=OutcomeResult.WIN, settled_at=datetime.now(timezone.utc), source="t"),
    )

    repository.append_event(
        session, bet_id=open_bet, event_type=EventType.DECISION_RECORDED, payload=_decision_payload(30.0)
    )
    repository.append_event(
        session,
        bet_id=open_bet,
        event_type=EventType.EXECUTION_RECORDED,
        payload=_execution_payload(stake=30.0, odds=1.5),
    )
    session.commit()

    state = repository.get_bankroll_state(session, total_capital=10_000.0)
    assert state.deployed == 30.0
    assert state.settled_pnl == 100.0
    assert state.current_balance == 10_100.0
