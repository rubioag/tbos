"""CE.4 — ActionPlan storage. Append-only, same discipline as everywhere else."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tbos.common import forbid_mutation
from tbos.db import Base

_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class ActionPlanRow(Base):
    __tablename__ = "action_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), unique=True, index=True, default=uuid.uuid4)
    edge_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    match_id: Mapped[str] = mapped_column(String(255), index=True)
    action_type: Mapped[str] = mapped_column(String(30), index=True)
    payload: Mapped[dict] = mapped_column(_JSONVariant)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(ActionPlanRow, "before_update", forbid_mutation)
event.listen(ActionPlanRow, "before_delete", forbid_mutation)
