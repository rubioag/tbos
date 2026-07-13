"""CE.5 — Execution Monitor (WAIT_FOR_PRICE / MONITOR_LIVE_CONDITION).

Built as a standalone, generically-testable mechanism: CE.4's v1 decision
space is {BET_NOW, DEFER, PASS} only (documented in ce4_decision/decision.py)
— ActionPlan carries no precondition/expiration fields yet because nothing
produces WAIT_FOR_PRICE today. This module is ready to be wired in the
moment CE.4 grows that capability, without needing to change.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from tbos.inf1_config.taxonomy import MonitorStatus


class PriceCondition(BaseModel):
    target_odds: float
    comparison: str  # "gte" | "lte"


class ExecutionMonitor(BaseModel):
    status: MonitorStatus
    condition: PriceCondition
    expires_at: datetime
    checked_at: datetime


def check_price_condition(
    condition: PriceCondition, current_odds: float, *, now: datetime, expires_at: datetime
) -> ExecutionMonitor:
    if now >= expires_at:
        return ExecutionMonitor(status=MonitorStatus.EXPIRED, condition=condition, expires_at=expires_at, checked_at=now)

    if condition.comparison == "gte":
        satisfied = current_odds >= condition.target_odds
    elif condition.comparison == "lte":
        satisfied = current_odds <= condition.target_odds
    else:
        raise ValueError(f"unknown comparison {condition.comparison!r}, expected 'gte' or 'lte'")

    status = MonitorStatus.SATISFIED if satisfied else MonitorStatus.PENDING
    return ExecutionMonitor(status=status, condition=condition, expires_at=expires_at, checked_at=now)
