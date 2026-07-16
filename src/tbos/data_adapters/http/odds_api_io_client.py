"""Thin HTTP client for odds-api.io (https://odds-api.io/) — replaces
The Odds API as TBOS's odds provider: verified via real API calls that
The Odds API's free tier does not cover ATP/WTA 250-level tournaments
(Bastad, Gstaad, Umag, Iasi, Athens all absent from its catalog), while
odds-api.io's `/v3/leagues?sport=tennis` lists all five with real,
non-zero event counts.

Same discipline as odds_api_client.py: owns only transport concerns
(timeouts, retries, rate-limit/error classification, structured
logging). Zero business logic — returns raw JSON, the adapter maps it to
RawOddsQuote. API key is never hardcoded — always read from an
environment variable via settings.py.
"""

from __future__ import annotations

import logging

import httpx

from tbos.data_adapters.contracts import EntityNotFoundError, SourceUnavailableError
from tbos.data_adapters.http.retry import retry_with_backoff
from tbos.settings import settings

logger = logging.getLogger("tbos.data_adapters.odds_api_io")

DEFAULT_BASE_URL = "https://api.odds-api.io/v3"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 0.5

# Free-tier restriction, confirmed via a real 403 response: "Access
# denied. You're allowed max 2 bookmakers. Allowed: Bet365, Betfair
# Exchange." Any other bookmaker name is rejected outright.
FREE_TIER_BOOKMAKERS = ("Bet365", "Betfair Exchange")


class OddsApiIoKeyMissingError(RuntimeError):
    """TBOS_ODDS_API_IO_KEY is not set. Raised only by from_env() — a
    clear, named failure instead of a generic ValueError or a traceback
    from deep inside httpx.
    """


class _RetryableHttpError(RuntimeError):
    """Internal-only signal: this failure is worth retrying. Never
    escapes the client — always reclassified into a typed contract error
    once retries are exhausted.
    """


class OddsApiIoClient:
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
    ) -> OddsApiIoClient:
        if not settings.odds_api_io_key:
            raise OddsApiIoKeyMissingError(
                "TBOS_ODDS_API_IO_KEY is not set. The odds-api.io adapter cannot run "
                "without it. Set it as an environment variable, or in a local .env file "
                "(already gitignored) before running. Never hardcode it in source."
            )
        return cls(
            api_key=settings.odds_api_io_key, base_url=base_url, timeout_seconds=timeout_seconds,
            max_retries=max_retries, backoff_base_seconds=backoff_base_seconds, transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OddsApiIoClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def list_leagues(self, *, sport: str = "tennis") -> list[dict]:
        url = f"{self._base_url}/leagues"
        params = {"sport": sport, "apiKey": self._api_key}
        return self._get_json(
            url, params, log_extra={"sport": sport},
            not_found_message=f"odds-api.io has no leagues for sport={sport!r}",
            operation_name=f"list_leagues(sport={sport!r})",
        )

    def list_events(self, *, sport: str = "tennis", league: str) -> list[dict]:
        url = f"{self._base_url}/events"
        params = {"sport": sport, "league": league, "apiKey": self._api_key}
        return self._get_json(
            url, params, log_extra={"sport": sport, "league": league},
            not_found_message=f"odds-api.io has no league={league!r} for sport={sport!r}",
            operation_name=f"list_events(league={league!r})",
        )

    def get_odds(
        self, *, sport: str = "tennis", event_id: str,
        bookmakers: tuple[str, ...] = FREE_TIER_BOOKMAKERS,
    ) -> dict:
        url = f"{self._base_url}/odds"
        params = {
            "sport": sport, "eventId": event_id,
            "bookmakers": ",".join(bookmakers), "apiKey": self._api_key,
        }
        result = self._get_json(
            url, params, log_extra={"sport": sport, "event_id": event_id},
            not_found_message=f"odds-api.io has no event_id={event_id!r}",
            operation_name=f"get_odds(event_id={event_id!r})",
        )
        return result  # type: ignore[return-value]  # this endpoint returns a single object, not a list

    def _get_json(
        self, url: str, params: dict[str, str], *,
        log_extra: dict[str, object], not_found_message: str, operation_name: str,
    ):
        def _do_request():
            try:
                response = self._client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise _RetryableHttpError(f"timeout calling odds-api.io: {exc}") from exc
            except httpx.TransportError as exc:
                raise _RetryableHttpError(f"connection error calling odds-api.io: {exc}") from exc

            logger.info(
                "odds_api_io response",
                extra={
                    "status_code": response.status_code,
                    "ratelimit_remaining": response.headers.get("x-ratelimit-remaining"),
                    "ratelimit_limit": response.headers.get("x-ratelimit-limit"),
                    **log_extra,
                },
            )

            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                raise EntityNotFoundError(not_found_message)
            if response.status_code in (401, 403):
                # Covers a bad/missing API key and the free-tier bookmaker
                # restriction alike — both are "this source is not usable
                # as configured", not "the entity doesn't exist".
                raise SourceUnavailableError(
                    f"odds-api.io authentication/authorization error "
                    f"(status={response.status_code}): {response.text[:200]}"
                )
            if response.status_code == 429:
                raise _RetryableHttpError("odds-api.io rate limit hit (status=429)")
            if response.status_code >= 500:
                raise _RetryableHttpError(
                    f"odds-api.io server error (status={response.status_code})"
                )
            if response.status_code == 400:
                # A malformed request on our side (missing/invalid
                # params) — not retryable, not "not found". Surfaced as
                # SourceUnavailableError since the contract has no
                # "caller error" category; the message carries the detail.
                raise SourceUnavailableError(
                    f"odds-api.io rejected the request (status=400): {response.text[:200]}"
                )

            raise SourceUnavailableError(
                f"odds-api.io unexpected status={response.status_code}: {response.text[:200]}"
            )

        try:
            return retry_with_backoff(
                _do_request,
                max_retries=self._max_retries,
                backoff_base_seconds=self._backoff_base_seconds,
                retryable=lambda exc: isinstance(exc, _RetryableHttpError),
                logger=logger,
                operation_name=operation_name,
            )
        except _RetryableHttpError as exc:
            raise SourceUnavailableError(str(exc)) from exc
