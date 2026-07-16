"""No real network calls: every test injects an httpx.MockTransport into
the OddsApiIoClient that backs the adapter. Fixture JSON shapes are taken
verbatim from real odds-api.io responses captured during the provider
migration investigation (ATP Bastad event 72661910), not invented.
"""

from __future__ import annotations

import httpx
import pytest

from tbos.data_adapters.contracts import EntityNotFoundError, SourceUnavailableError
from tbos.data_adapters.http.odds_api_io_adapter import OddsApiIoAdapter
from tbos.data_adapters.http.odds_api_io_client import OddsApiIoClient
from tbos.inf1_config.taxonomy import InstrumentType

REAL_EVENT_ODDS_RESPONSE = {
    "id": 72661910,
    "home": "De Jong, Jesper",
    "away": "Baez, Sebastian",
    "homeId": 310974,
    "awayId": 257721,
    "date": "2026-07-16T14:40:00Z",
    "status": "pending",
    "sport": {"name": "Tennis", "slug": "tennis"},
    "league": {"name": "ATP - Bastad, Sweden", "slug": "atp-bastad-sweden"},
    "bookmakers": {
        "Bet365": [
            {
                "name": "ML",
                "updatedAt": "2026-07-16T13:26:33.656Z",
                "odds": [{"home": "1.80", "away": "2.00"}],
            },
            {
                "name": "Totals (Games)",
                "updatedAt": "2026-07-14T22:41:36.84Z",
                "odds": [{"hdp": 22.5, "over": "1.80", "under": "1.90"}],
            },
        ],
    },
}


def _adapter(handler, **kwargs) -> OddsApiIoAdapter:
    client = OddsApiIoClient(api_key="test_key", transport=httpx.MockTransport(handler))
    return OddsApiIoAdapter(client, **kwargs)


def test_maps_real_ml_market_to_two_quotes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=REAL_EVENT_ODDS_RESPONSE)

    adapter = _adapter(handler)
    quotes = adapter.fetch_odds("72661910", InstrumentType.MONEYLINE)

    assert len(quotes) == 2
    by_selection = {q.selection: q for q in quotes}
    assert by_selection["player_a"].odds == 1.80
    assert by_selection["player_b"].odds == 2.00
    assert all(q.book_id == "Bet365" for q in quotes)
    assert all(q.match_id == "72661910" for q in quotes)
    assert all(q.instrument_type == InstrumentType.MONEYLINE for q in quotes)


def test_non_ml_markets_ignored() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=REAL_EVENT_ODDS_RESPONSE)

    adapter = _adapter(handler)
    quotes = adapter.fetch_odds("72661910", InstrumentType.MONEYLINE)
    # Only the "ML" market's 2 outcomes — "Totals (Games)" must not leak in.
    assert len(quotes) == 2


def test_empty_bookmakers_returns_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 1, "bookmakers": {}})

    adapter = _adapter(handler)
    assert adapter.fetch_odds("1", InstrumentType.MONEYLINE) == []


def test_non_moneyline_instrument_raises_entity_not_found() -> None:
    adapter = _adapter(lambda r: httpx.Response(200, json={}))
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_odds("1", InstrumentType.HANDICAP)


def test_event_not_found_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "No event found"})

    adapter = _adapter(handler)
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_odds("ghost", InstrumentType.MONEYLINE)

def test_multiple_bookmakers_each_produce_two_quotes() -> None:
    event = {
        "id": 1,
        "bookmakers": {
            "Bet365": [{"name": "ML", "updatedAt": "2026-07-16T13:26:33.656Z", "odds": [{"home": "1.5", "away": "2.5"}]}],
            "Betfair Exchange": [{"name": "ML", "updatedAt": "2026-07-16T13:26:41.329Z", "odds": [{"home": "1.51", "away": "2.6"}]}],
        },
    }
    adapter = _adapter(lambda r: httpx.Response(200, json=event))
    quotes = adapter.fetch_odds("1", InstrumentType.MONEYLINE)
    assert len(quotes) == 4
    assert {q.book_id for q in quotes} == {"Bet365", "Betfair Exchange"}


def test_odds_entry_missing_one_side_skipped_not_fabricated() -> None:
    event = {
        "id": 1,
        "bookmakers": {
            "Betfair Exchange": [
                {
                    "name": "ML",
                    "updatedAt": "2026-07-16T13:26:41.329Z",
                    "odds": [{"home": "1.31", "layHome": "1.33"}],  # no "away" price
                }
            ],
        },
    }
    adapter = _adapter(lambda r: httpx.Response(200, json=event))
    assert adapter.fetch_odds("1", InstrumentType.MONEYLINE) == []


def test_malformed_market_raises_source_unavailable() -> None:
    event = {"id": 1, "bookmakers": {"Bet365": [{"name": "ML", "odds": [{"home": "1.8", "away": "2.0"}]}]}}  # missing updatedAt
    adapter = _adapter(lambda r: httpx.Response(200, json=event))
    with pytest.raises(SourceUnavailableError):
        adapter.fetch_odds("1", InstrumentType.MONEYLINE)
