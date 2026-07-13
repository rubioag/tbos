"""CE.1 repository — the only code path allowed to publish/read Snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from tbos.ce1_data.models import Snapshot


def publish_snapshot(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    fields: BaseModel,
    config_version_id: uuid.UUID,
    supersedes: uuid.UUID | None = None,
    reconstructed: bool = False,
    as_of_timestamp: datetime | None = None,
) -> Snapshot:
    row = Snapshot(
        entity_type=entity_type,
        entity_id=entity_id,
        fields=fields.model_dump(mode="json"),
        config_version_id=config_version_id,
        supersedes=supersedes,
        reconstructed=reconstructed,
        as_of_timestamp=as_of_timestamp,
    )
    session.add(row)
    session.flush()
    return row


def get_snapshot(session: Session, snapshot_id: uuid.UUID) -> Snapshot | None:
    stmt = select(Snapshot).where(Snapshot.snapshot_id == snapshot_id)
    return session.execute(stmt).scalar_one_or_none()


def get_latest_snapshot(session: Session, entity_type: str, entity_id: str) -> Snapshot | None:
    """Most recently published snapshot for this entity — live use only.
    For historical/backtest use, see get_snapshot_as_of (anti-lookahead).
    """
    stmt = (
        select(Snapshot)
        .where(Snapshot.entity_type == entity_type, Snapshot.entity_id == entity_id)
        .order_by(Snapshot.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_snapshot_as_of(
    session: Session, entity_type: str, entity_id: str, as_of: datetime
) -> Snapshot | None:
    """The snapshot that was live at time `as_of` — the only correct way to
    read CE.1 data during backtesting. Never returns a snapshot published
    after `as_of` (Historical Data Pipeline §B anti-lookahead guarantee).
    """
    stmt = (
        select(Snapshot)
        .where(
            Snapshot.entity_type == entity_type,
            Snapshot.entity_id == entity_id,
            Snapshot.published_at <= as_of,
        )
        .order_by(Snapshot.published_at.desc(), Snapshot.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_snapshot_lineage(session: Session, snapshot_id: uuid.UUID) -> list[Snapshot]:
    """Walk the `supersedes` chain back to the original snapshot — full
    correction history for a single entity_id, oldest first.
    """
    chain: list[Snapshot] = []
    current = get_snapshot(session, snapshot_id)
    while current is not None:
        chain.append(current)
        current = get_snapshot(session, current.supersedes) if current.supersedes else None
    return list(reversed(chain))
