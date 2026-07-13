"""CE.2.8 — Shadow Output Storage. Append-only, same discipline as every
other event/snapshot table in TBOS. Feeds INF.3 calibration once enough
shadow runs accumulate; never consumed by the live Ensemble Aggregator
(enforced structurally in ensemble.py via execution_mode).
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


class ShadowOutputRow(Base):
    __tablename__ = "shadow_outputs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    model_id: Mapped[str] = mapped_column(String(100), index=True)
    model_version: Mapped[str] = mapped_column(String(50))
    match_id: Mapped[str] = mapped_column(String(255), index=True)
    output: Mapped[dict] = mapped_column(_JSONVariant)
    execution_mode: Mapped[str] = mapped_column(String(20))
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(ShadowOutputRow, "before_update", forbid_mutation)
event.listen(ShadowOutputRow, "before_delete", forbid_mutation)
