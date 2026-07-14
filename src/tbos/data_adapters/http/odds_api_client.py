"""Thin HTTP client for The Odds API (https://the-odds-api.com/). Owns
only transport concerns — timeouts, retries, rate-limit/error
classification, structured logging. Zero business logic: returns raw
JSON, the adapter maps it to RawOddsQuote.

API key is never hardcoded — always supplied by the caller, which reads
it from an environment variable (see settings.py).
"""

from __future__ import annotations

import logging

import httpx

from tbos.data_adapters.contracts import EntityNotFoundError, SourceUnavailableError
from tbos.data_adapters.http.retry import retry_with_backoff
from tbos.settings import settings

logger = logging.getLogger("tbos.data_adapters.odds_api")

DEFAULT_BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 0.5


class OddsApiKeyMissingError(RuntimeError):
    """TBOS_ODDS_API_KEY is not set. Raised only by from_env() — a clear,
    named failure instead of a generic ValueError or a confusing
    traceback from deep inside the HTTP layer.
    """


class _RetryableHttpError(RuntimeError):
    """Internal-only signal: this failure is worth retrying. Never
    escapes the client — always reclassified into a typed contract error
    once retries are exhausted.
    """


class OddsApiClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "api_key must not be empty — read it from an env var, never hardcode it"
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> OddsApiClient:
        """Construct from TBOS_ODDS_API_KEY. Fails fast with a named,
        actionable error if it isn't set — never a bare ValueError or a
        traceback from inside httpx.
        """
        if not settings.odds_api_key:
            raise OddsApiKeyMissingError(
                "TBOS_ODDS_API_KEY is not set. The Odds API adapter cannot run without it. "
                "Set it as an environment variable, or in a local .env file (already "
                "gitignored) before running. Never hardcode it in source."
            )
        return cls(
            api_key=settings.odds_api_key, base_url=base_url, timeout_seconds=timeout_seconds,
            max_retries=max_retries, backoff_base_seconds=backoff_base_seconds, transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OddsApiClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_odds(
        self, sport_key: str, *,
        regions: str = "eu", markets: str = "h2h", odds_format: str = "decimal",
    ) -> list[dict]:
        url = f"{self._base_url}/sports/{sport_key}/odds/"
        params = {
            "apiKey": self._api_key, "regions": regions,
            "markets": markets, "oddsFormat": odds_format,
        }

        def _do_request() -> list[dict]:
            try:
                response = self._client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise _RetryableHttpError(f"timeout calling The Odds API: {exc}") from exc
            except httpx.TransportError as exc:
                raise _RetryableHttpError(f"connection error calling The Odds API: {exc}") from exc

            logger.info(
                "the_odds_api response",
                extra={
                    "status_code": response.status_code,
                    "requests_remaining": response.headers.get("x-requests-remaining"),
                    "requests_used": response.headers.get("x-requests-used"),
                    "sport_key": sport_key,
                },
            )

            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                raise EntityNotFoundError(f"The Odds API has no sport_key={sport_key!r}")
            if response.status_code in (401, 403):
                # Covers both a bad API key and an exhausted free-tier
                # quota — The Odds API does not reliably distinguish the
                # two in the response body, so this is deliberately not
                # split into two error types (would be guessing).
                raise SourceUnavailableError(
                    f"The Odds API authentication or quota error (status={response.status_code})"
                )
            if response.status_code == 429:
                raise _RetryableHttpError("The Odds API rate limit hit (status=429)")
            if response.status_code >= 500:
                raise _RetryableHttpError(
                    f"The Odds API server error (status={response.status_code})"
                )

            raise SourceUnavailableError(
                f"The Odds API unexpected status={response.status_code}: {response.text[:200]}"
            )

        try:
            return retry_with_backoff(
                _do_request,
                max_retries=self._max_retries,
                backoff_base_seconds=self._backoff_base_seconds,
                retryable=lambda exc: isinstance(exc, _RetryableHttpError),
                logger=logger,
                operation_name=f"get_odds(sport_key={sport_key!r})",
            )
        except _RetryableHttpError as exc:
            raise SourceUnavailableError(str(exc)) from exc
