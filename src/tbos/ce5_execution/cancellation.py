"""CE.5 — Cancellation builders. Every cancellation carries a structured
reason and the specific conditions that weren't met — never an
improvised substitute trade (Execution Intent Principle: if the plan
can't be filled as specified, it's cancelled, not silently redirected to
a different instrument).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from tbos.ce5_execution.schemas import CancellationRecord
from tbos.inf1_config.taxonomy import CancellationReason

CE5_ENGINE_VERSION = "1.0.0"


def build_cancellation(
    action_plan_id: uuid.UUID, *, reason: CancellationReason, conditions_unmet: list[str], as_of: datetime
) -> CancellationRecord:
    return CancellationRecord(
        action_plan_id=action_plan_id, reason=reason, conditions_unmet=conditions_unmet,
        cancellation_timestamp=as_of, ce5_engine_version=CE5_ENGINE_VERSION,
    )


def liquidity_insufficient_cancellation(
    action_plan_id: uuid.UUID, *, target_stake: float, filled_stake: float, as_of: datetime
) -> CancellationRecord:
    return build_cancellation(
        action_plan_id, reason=CancellationReason.LIQUIDITY_INSUFFICIENT,
        conditions_unmet=[f"filled {filled_stake:.2f} of target {target_stake:.2f}"], as_of=as_of,
    )


def precondition_timeout_cancellation(action_plan_id: uuid.UUID, *, as_of: datetime) -> CancellationRecord:
    return build_cancellation(
        action_plan_id, reason=CancellationReason.PRECONDITION_TIMEOUT,
        conditions_unmet=["precondition never satisfied before expiration"], as_of=as_of,
    )
