"""No real network calls: every test injects an httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest

from tbos.data_adapters.contracts import EntityNotFoundError, SourceUnavailableError
from tbos.data_adapters.http.odds_api_io_client import OddsApiIoClient, OddsApiIoKeyMissingError
from tbos.settings import settings


def _client(handler, **kwargs) -> OddsApiIoClient:
    transport = httpx.MockTransport(handler)
    return OddsApiIoClient(api_key="test_key", transport=transport, **kwargs)


def test_empty_api_key_rejected() -> None:
    with pytest.raises(ValueError):
        OddsApiIoClient(api_key="")


def test_from_env_missing_key_raises_named_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "odds_api_io_key", None)
    with pytest.raises(OddsApiIoKeyMissingError, match="TBOS_ODDS_API_IO_KEY"):
        OddsApiIoClient.from_env()


def test_from_env_present_key_constructs_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "odds_api_io_key", "real_key")
    client = OddsApiIoClient.from_env()
    assert client is not None
    client.close()


def test_list_leagues_returns_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/leagues"
        assert request.url.params["sport"] == "tennis"
        return httpx.Response(200, json=[{"name": "ATP - Bastad, Sweden", "slug": "atp-bastad-sweden", "eventsCount": 9}])

    client = _client(handler)
    result = client.list_leagues()
    assert result == [{"name": "ATP - Bastad, Sweden", "slug": "atp-bastad-sweden", "eventsCount": 9}]


def test_list_events_returns_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/events"
        assert request.url.params["league"] == "atp-bastad-sweden"
        return httpx.Response(200, json=[{"id": 1, "home": "A", "away": "B", "status": "pending"}])

    client = _client(handler)
    result = client.list_events(league="atp-bastad-sweden")
    assert result == [{"id": 1, "home": "A", "away": "B", "status": "pending"}]


def test_get_odds_returns_json_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/odds"
        assert request.url.params["eventId"] == "123"
        assert request.url.params["bookmakers"] == "Bet365,Betfair Exchange"
        return httpx.Response(200, json={"id": 123, "bookmakers": {}})

    client = _client(handler)
    result = client.get_odds(event_id="123")
    assert result == {"id": 123, "bookmakers": {}}


def test_get_odds_404_raises_entity_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "No event found"})

    client = _client(handler)
    with pytest.raises(EntityNotFoundError):
        client.get_odds(event_id="ghost")


def test_401_raises_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "You need to provide a valid apiKey"})

    client = _client(handler)
    with pytest.raises(SourceUnavailableError):
        client.list_leagues()


def test_403_bookmaker_restriction_raises_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "Access denied. You're allowed max 2 bookmakers."})

    client = _client(handler)
    with pytest.raises(SourceUnavailableError):
        client.get_odds(event_id="123", bookmakers=("Pinnacle",))


def test_400_raises_source_unavailable_not_retryable() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "Missing bookmakers"})

    client = _client(handler)
    with pytest.raises(SourceUnavailableError):
        client.get_odds(event_id="123")
    assert calls["n"] == 1  # not retried — 400 is a caller error, not transient


def test_429_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=[])

    client = _client(handler, max_retries=2, backoff_base_seconds=0.0)
    result = client.list_leagues()
    assert result == []
    assert calls["n"] == 2
