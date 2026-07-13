from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tbos.paper_trading.lifecycle import validate_transition
from tbos.paper_trading.models import (
    ApprovalRecordRow,
    PaperTradingBetRow,
    PaperTradingRunEventRow,
    PaperTradingRunRow,
)
from tbos.paper_trading.schemas import ApprovalRecord, PaperTradingBetRecord, PaperTradingRun
from tbos.inf1_config.taxonomy import PaperTradingStatus


def create_run(session: Session, run: PaperTradingRun) -> PaperTradingRunRow:
    row = PaperTradingRunRow(
        id=run.run_id, protocol_version=run.protocol_version,
        config_version_id_at_start=run.config_version_id_at_start, status=run.status.value,
    )
    session.add(row)
    session.flush()
    return row


def get_run(session: Session, run_id: uuid.UUID) -> PaperTradingRunRow | None:
    return session.get(PaperTradingRunRow, run_id)


def transition_run(
    session: Session, run_id: uuid.UUID, target: PaperTradingStatus, *, reason: str
) -> PaperTradingRunRow:
    row = get_run(session, run_id)
    if row is None:
        raise ValueError(f"unknown run {run_id}")

    current = PaperTradingStatus(row.status)
    validate_transition(current, target)

    session.add(PaperTradingRunEventRow(run_id=run_id, from_status=current.value, to_status=target.value, reason=reason))
    row.status = target.value
    session.flush()
    return row


def record_bet(session: Session, bet: PaperTradingBetRecord) -> PaperTradingBetRow:
    row = PaperTradingBetRow(
        run_id=bet.run_id, match_id=bet.match_id, payload=bet.model_dump(mode="json"),
        structural_error=bet.structural_error,
    )
    session.add(row)
    session.flush()
    return row


def list_bets_for_run(session: Session, run_id: uuid.UUID) -> list[PaperTradingBetRow]:
    stmt = select(PaperTradingBetRow).where(PaperTradingBetRow.run_id == run_id)
    return list(session.execute(stmt).scalars().all())


def record_approval(session: Session, record: ApprovalRecord) -> ApprovalRecordRow:
    row = ApprovalRecordRow(run_id=record.run_id, payload=record.model_dump(mode="json"))
    session.add(row)
    session.flush()
    return row


def list_approvals_for_run(session: Session, run_id: uuid.UUID) -> list[ApprovalRecordRow]:
    stmt = select(ApprovalRecordRow).where(ApprovalRecordRow.run_id == run_id)
    return list(session.execute(stmt).scalars().all())
