from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tbos.ce4_decision.models import ActionPlanRow
from tbos.ce4_decision.schemas import ActionPlan


def publish_action_plan(session: Session, plan: ActionPlan) -> ActionPlanRow:
    row = ActionPlanRow(
        action_plan_id=plan.action_plan_id, edge_id=plan.edge_id, match_id=plan.match_id,
        action_type=plan.action_type.value, payload=plan.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    return row


def get_action_plan(session: Session, action_plan_id: uuid.UUID) -> ActionPlanRow | None:
    stmt = select(ActionPlanRow).where(ActionPlanRow.action_plan_id == action_plan_id)
    return session.execute(stmt).scalar_one_or_none()


def list_for_match(session: Session, match_id: str) -> list[ActionPlanRow]:
    stmt = select(ActionPlanRow).where(ActionPlanRow.match_id == match_id)
    return list(session.execute(stmt).scalars().all())
