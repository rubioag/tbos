"""CE.5 — Execution outcome storage. Append-only. One table, discriminated
by `outcome_type` (EXECUTED | CANCELLED) — both are equally valid, final
outcomes of attempting to fill an ActionPlan.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tbos.common import forbid_mutation
from tbos.db import Base

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class ExecutionOutcomeRow(Base):
    __tablename__ = "execution_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    outcome_type: Mapped[str] = mapped_column(String(20))  # EXECUTED | CANCELLED
    payload: Mapped[dict] = mapped_column(_JSONVariant)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(ExecutionOutcomeRow, "before_update", forbid_mutation)
event.listen(ExecutionOutcomeRow, "before_delete", forbid_mutation)
