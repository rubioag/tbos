"""Generic exponential-backoff retry helper, shared by any HTTP-backed
adapter (currently only The Odds API, but not specific to it).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable


class RetryExhausted(RuntimeError):
    """All retry attempts failed; wraps the last underlying exception."""


def retry_with_backoff[T](
    fn: Callable[[], T],
    *,
    max_retries: int,
    backoff_base_seconds: float,
    retryable: Callable[[Exception], bool],
    logger: logging.Logger,
    operation_name: str,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    attempt = 0
    last_exc: Exception | None = None

    while attempt <= max_retries:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - reclassified below via `retryable`
            last_exc = exc
            if not retryable(exc) or attempt >= max_retries:
                raise
            delay = backoff_base_seconds * (2**attempt)
            logger.warning(
                "retrying %s after error (attempt %d/%d), backing off %.2fs",
                operation_name, attempt + 1, max_retries, delay,
                extra={
                    "operation": operation_name, "attempt": attempt + 1, "max_retries": max_retries,
                    "delay_seconds": delay, "error": str(exc),
                },
            )
            sleep(delay)
            attempt += 1

    # Unreachable in practice (the loop always returns or raises), but
    # keeps type-checkers honest and gives a clear failure if it ever is.
    raise RetryExhausted(f"{operation_name} exhausted retries") from last_exc
