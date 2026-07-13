"""CE.6 — CLVRecord storage. Append-only."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tbos.common import forbid_mutation
from tbos.db import Base

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class CLVRecordRow(Base):
    __tablename__ = "clv_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    clv_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), unique=True, index=True, default=uuid.uuid4)
    action_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    match_id: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(_JSONVariant)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(CLVRecordRow, "before_update", forbid_mutation)
event.listen(CLVRecordRow, "before_delete", forbid_mutation)
