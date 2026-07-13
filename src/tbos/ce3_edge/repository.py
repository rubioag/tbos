"""CE.3 repository. Publishing never orders/ranks results across a match —
`list_for_match` returns an unordered set, matching Decision Independence.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tbos.ce3_edge.models import EdgeDescriptionRow
from tbos.ce3_edge.schemas import EdgeDescription


def publish_edge_description(session: Session, description: EdgeDescription) -> EdgeDescriptionRow:
    row = EdgeDescriptionRow(
        edge_id=description.edge_id, match_id=description.match_id,
        instrument_type=description.instrument_type.value, book_id=description.book_id,
        payload=description.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    return row


def get_edge_description(session: Session, edge_id: uuid.UUID) -> EdgeDescriptionRow | None:
    stmt = select(EdgeDescriptionRow).where(EdgeDescriptionRow.edge_id == edge_id)
    return session.execute(stmt).scalar_one_or_none()


def list_for_match(session: Session, match_id: str) -> list[EdgeDescriptionRow]:
    stmt = select(EdgeDescriptionRow).where(EdgeDescriptionRow.match_id == match_id)
    return list(session.execute(stmt).scalars().all())
