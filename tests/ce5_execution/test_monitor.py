from datetime import datetime, timedelta, timezone

from tbos.ce5_execution.monitor import PriceCondition, check_price_condition
from tbos.inf1_config.taxonomy import MonitorStatus

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
EXPIRES = NOW + timedelta(hours=1)


def test_gte_condition_satisfied_when_odds_reach_target() -> None:
    condition = PriceCondition(target_odds=1.90, comparison="gte")
    result = check_price_condition(condition, 1.95, now=NOW, expires_at=EXPIRES)
    assert result.status == MonitorStatus.SATISFIED


def test_gte_condition_pending_when_odds_below_target() -> None:
    condition = PriceCondition(target_odds=1.90, comparison="gte")
    result = check_price_condition(condition, 1.80, now=NOW, expires_at=EXPIRES)
    assert result.status == MonitorStatus.PENDING


def test_lte_condition_satisfied_when_odds_drop_to_target() -> None:
    condition = PriceCondition(target_odds=1.80, comparison="lte")
    result = check_price_condition(condition, 1.75, now=NOW, expires_at=EXPIRES)
    assert result.status == MonitorStatus.SATISFIED


def test_expired_takes_priority_over_satisfied() -> None:
    condition = PriceCondition(target_odds=1.90, comparison="gte")
    result = check_price_condition(condition, 2.00, now=EXPIRES + timedelta(seconds=1), expires_at=EXPIRES)
    assert result.status == MonitorStatus.EXPIRED


def test_unknown_comparison_raises() -> None:
    import pytest

    condition = PriceCondition(target_odds=1.90, comparison="equals")
    with pytest.raises(ValueError):
        check_price_condition(condition, 1.90, now=NOW, expires_at=EXPIRES)
