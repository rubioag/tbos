from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tbos.ce6_clv.models import CLVRecordRow
from tbos.ce6_clv.schemas import CLVRecord


def publish_clv_record(session: Session, record: CLVRecord) -> CLVRecordRow:
    row = CLVRecordRow(
        clv_id=record.clv_id, action_plan_id=record.action_plan_id, match_id=record.match_id,
        payload=record.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    return row


def get_clv_record(session: Session, clv_id: uuid.UUID) -> CLVRecordRow | None:
    stmt = select(CLVRecordRow).where(CLVRecordRow.clv_id == clv_id)
    return session.execute(stmt).scalar_one_or_none()


def list_for_match(session: Session, match_id: str) -> list[CLVRecordRow]:
    stmt = select(CLVRecordRow).where(CLVRecordRow.match_id == match_id)
    return list(session.execute(stmt).scalars().all())
