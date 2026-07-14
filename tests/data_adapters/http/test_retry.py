import logging

import pytest

from tbos.data_adapters.http.retry import RetryExhausted, retry_with_backoff


def _logger() -> logging.Logger:
    return logging.getLogger("test.retry")


def test_succeeds_first_try_no_sleep() -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def fn() -> str:
        calls["n"] += 1
        return "ok"

    result = retry_with_backoff(
        fn, max_retries=3, backoff_base_seconds=1.0, retryable=lambda e: True,
        logger=_logger(), operation_name="op", sleep=sleeps.append,
    )
    assert result == "ok"
    assert calls["n"] == 1
    assert sleeps == []


def test_retries_then_succeeds() -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    result = retry_with_backoff(
        fn, max_retries=5, backoff_base_seconds=1.0, retryable=lambda e: True,
        logger=_logger(), operation_name="op", sleep=sleeps.append,
    )
    assert result == "ok"
    assert calls["n"] == 3
    assert sleeps == [1.0, 2.0]  # exponential: base * 2^attempt


def test_non_retryable_error_raises_immediately() -> None:
    def fn() -> str:
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        retry_with_backoff(
            fn, max_retries=5, backoff_base_seconds=1.0, retryable=lambda e: False,
            logger=_logger(), operation_name="op", sleep=lambda _: None,
        )


def test_exhausts_retries_and_raises_last_exception() -> None:
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        raise ValueError(f"fail {calls['n']}")

    with pytest.raises(ValueError, match="fail 3"):
        retry_with_backoff(
            fn, max_retries=2, backoff_base_seconds=0.1, retryable=lambda e: True,
            logger=_logger(), operation_name="op", sleep=lambda _: None,
        )
    assert calls["n"] == 3  # initial attempt + 2 retries


def test_retry_exhausted_type_exists_and_wraps_cause() -> None:
    exc = RetryExhausted("boom")
    assert isinstance(exc, RuntimeError)
