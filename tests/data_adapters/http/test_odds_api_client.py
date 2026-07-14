"""No real network calls: every test injects an httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest

from tbos.data_adapters.contracts import EntityNotFoundError, SourceUnavailableError
from tbos.data_adapters.http.odds_api_client import OddsApiClient


def _client(handler, **kwargs) -> OddsApiClient:
    transport = httpx.MockTransport(handler)
    return OddsApiClient(api_key="test_key", transport=transport, **kwargs)


def test_empty_api_key_rejected() -> None:
    with pytest.raises(ValueError):
        OddsApiClient(api_key="")


def test_successful_response_returns_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apiKey"] == "test_key"
        assert request.url.params["markets"] == "h2h"
        return httpx.Response(200, json=[{"id": "evt1"}], headers={"x-requests-remaining": "499"})

    client = _client(handler)
    result = client.get_odds("tennis_atp_wimbledon")
    assert result == [{"id": "evt1"}]


def test_404_raises_entity_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = _client(handler)
    with pytest.raises(EntityNotFoundError):
        client.get_odds("unknown_sport")


def test_401_raises_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    client = _client(handler)
    with pytest.raises(SourceUnavailableError):
        client.get_odds("tennis_atp_wimbledon")


def test_429_retries_then_raises_source_unavailable_after_exhaustion() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, text="rate limited")

    client = _client(handler, max_retries=2, backoff_base_seconds=0.0)
    with pytest.raises(SourceUnavailableError):
        client.get_odds("tennis_atp_wimbledon")
    assert calls["n"] == 3  # initial + 2 retries


def test_429_then_200_succeeds_after_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json=[{"id": "evt1"}])

    client = _client(handler, max_retries=2, backoff_base_seconds=0.0)
    result = client.get_odds("tennis_atp_wimbledon")
    assert result == [{"id": "evt1"}]
    assert calls["n"] == 2


def test_500_is_retryable() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="server error")

    client = _client(handler, max_retries=1, backoff_base_seconds=0.0)
    with pytest.raises(SourceUnavailableError):
        client.get_odds("tennis_atp_wimbledon")
    assert calls["n"] == 2  # initial + 1 retry


def test_timeout_is_retryable_then_raises_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = _client(handler, max_retries=1, backoff_base_seconds=0.0)
    with pytest.raises(SourceUnavailableError):
        client.get_odds("tennis_atp_wimbledon")


def test_unexpected_status_raises_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="unprocessable")

    client = _client(handler)
    with pytest.raises(SourceUnavailableError):
        client.get_odds("tennis_atp_wimbledon")
