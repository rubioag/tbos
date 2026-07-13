from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tbos.ce5_execution.models import ExecutionOutcomeRow
from tbos.ce5_execution.schemas import CancellationRecord, ExecutionRecord


def publish_outcome(session: Session, outcome: ExecutionRecord | CancellationRecord) -> ExecutionOutcomeRow:
    outcome_type = "EXECUTED" if isinstance(outcome, ExecutionRecord) else "CANCELLED"
    row = ExecutionOutcomeRow(
        action_plan_id=outcome.action_plan_id, outcome_type=outcome_type, payload=outcome.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    return row


def get_outcomes_for_plan(session: Session, action_plan_id: uuid.UUID) -> list[ExecutionOutcomeRow]:
    stmt = select(ExecutionOutcomeRow).where(ExecutionOutcomeRow.action_plan_id == action_plan_id)
    return list(session.execute(stmt).scalars().all())
