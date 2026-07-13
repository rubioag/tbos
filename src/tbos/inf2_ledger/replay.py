"""INF.2 — Replay. `BetRecord` is always a materialized *view*, never a
source of truth in itself (spec §C): it is rebuilt by folding a bet's
event stream, in timeline order, every time it's requested.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from tbos.inf1_config.taxonomy import BetStatus, EventType, OutcomeResult
from tbos.inf2_ledger.events import (
    CancellationRecordedPayload,
    CLVRecordedPayload,
    CorrectionRecordedPayload,
    DecisionRecordedPayload,
    EVENT_PAYLOAD_SCHEMAS,
    ExecutionRecordedPayload,
    OutcomeRecordedPayload,
)
from tbos.inf2_ledger.models import Event


class CorrectionRecord(BaseModel):
    corrects_event_id: uuid.UUID
    reason: str
    replacement_event_id: uuid.UUID | None
    timestamp: datetime


class BetRecord(BaseModel):
    bet_id: uuid.UUID
    status: BetStatus

    decision: DecisionRecordedPayload | None = None
    execution: ExecutionRecordedPayload | None = None
    cancellation: CancellationRecordedPayload | None = None
    clv: CLVRecordedPayload | None = None
    outcome: OutcomeRecordedPayload | None = None
    corrections: list[CorrectionRecord] = []

    event_count: int = 0
    last_event_id: uuid.UUID | None = None


class EmptyEventStream(RuntimeError):
    """Raised when replay is attempted on a bet_id with zero events."""


def _decode(event_row: Event) -> BaseModel:
    schema = EVENT_PAYLOAD_SCHEMAS[event_row.event_type]
    return schema.model_validate(event_row.payload)


def replay_bet(events: list[Event]) -> BetRecord:
    """Fold a bet's full event stream (already ordered by timeline index,
    i.e. Event.id ascending) into its current materialized state.

    Rule: for singleton event types (DECISION/EXECUTION/CANCELLATION/CLV/
    OUTCOME), the *latest* occurrence wins — this is how a correction takes
    effect: CORRECTION_RECORDED never mutates the original event, it just
    points at a *new* event of the same type appended afterward, and that
    new event naturally becomes the effective state under latest-wins.
    """
    if not events:
        raise EmptyEventStream("replay_bet called with an empty event list")

    bet_id = events[0].bet_id
    record = BetRecord(bet_id=bet_id, status=BetStatus.DECIDED)

    for row in events:
        payload = _decode(row)
        record.event_count += 1
        record.last_event_id = row.event_id

        match row.event_type:
            case EventType.DECISION_RECORDED:
                record.decision = payload  # type: ignore[assignment]
            case EventType.EXECUTION_RECORDED:
                record.execution = payload  # type: ignore[assignment]
                record.cancellation = None  # a later execution supersedes an earlier cancellation
            case EventType.CANCELLATION_RECORDED:
                record.cancellation = payload  # type: ignore[assignment]
            case EventType.CLV_RECORDED:
                record.clv = payload  # type: ignore[assignment]
            case EventType.OUTCOME_RECORDED:
                record.outcome = payload  # type: ignore[assignment]
            case EventType.CORRECTION_RECORDED:
                correction: CorrectionRecordedPayload = payload  # type: ignore[assignment]
                record.corrections.append(
                    CorrectionRecord(
                        corrects_event_id=correction.corrects_event_id,
                        reason=correction.reason,
                        replacement_event_id=correction.replacement_event_id,
                        timestamp=row.timestamp,
                    )
                )
            case _:  # pragma: no cover - guarded by EVENT_PAYLOAD_SCHEMAS at write time
                raise ValueError(f"unknown event_type {row.event_type!r}")

    record.status = _derive_status(record)
    return record


def _derive_status(record: BetRecord) -> BetStatus:
    if record.outcome is not None:
        return BetStatus.SETTLED
    if record.cancellation is not None and record.execution is None:
        return BetStatus.CANCELLED
    if record.execution is not None:
        return BetStatus.AWAITING_SETTLEMENT
    return BetStatus.DECIDED


class BankrollState(BaseModel):
    total_capital: float
    deployed: float
    settled_pnl: float
    current_balance: float


def _settled_pnl(record: BetRecord) -> float:
    if record.outcome is None or record.execution is None:
        return 0.0
    stake = record.execution.actual_stake_total
    avg_odds = (
        sum(s.odds * s.stake_portion for s in record.execution.actual_odds_per_split) / stake
        if stake > 0
        else 0.0
    )
    if record.outcome.result == OutcomeResult.WIN:
        return stake * (avg_odds - 1)
    if record.outcome.result == OutcomeResult.LOSS:
        return -stake
    return 0.0  # VOID | PUSH


def compute_bankroll_state(records: list[BetRecord], *, total_capital: float) -> BankrollState:
    deployed = sum(
        r.execution.actual_stake_total
        for r in records
        if r.status == BetStatus.AWAITING_SETTLEMENT and r.execution is not None
    )
    settled_pnl = sum(_settled_pnl(r) for r in records if r.status == BetStatus.SETTLED)
    return BankrollState(
        total_capital=total_capital,
        deployed=deployed,
        settled_pnl=settled_pnl,
        current_balance=total_capital + settled_pnl,
    )
