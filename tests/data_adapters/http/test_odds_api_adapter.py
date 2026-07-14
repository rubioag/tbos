"""No real network calls: every test injects an httpx.MockTransport into
the OddsApiClient that backs the adapter.
"""

from __future__ import annotations

import httpx
import pytest

from tbos.data_adapters.contracts import EntityNotFoundError, SourceUnavailableError
from tbos.data_adapters.http.odds_api_adapter import OddsApiAdapter, OddsApiEventRef
from tbos.data_adapters.http.odds_api_client import OddsApiClient
from tbos.inf1_config.taxonomy import InstrumentType

EVENT_JSON = {
    "id": "evt1",
    "sport_key": "tennis_atp_wimbledon",
    "commence_time": "2026-07-14T12:00:00Z",
    "home_team": "Player A",
    "away_team": "Player B",
    "bookmakers": [
        {
            "key": "pinnacle",
            "title": "Pinnacle",
            "last_update": "2026-07-14T10:00:00Z",
            "markets": [
                {
                    "key": "h2h",
                    "last_update": "2026-07-14T10:00:00Z",
                    "outcomes": [
                        {"name": "Player A", "price": 1.9},
                        {"name": "Player B", "price": 2.0},
                    ],
                }
            ],
        }
    ],
}


def _adapter(events_response: list[dict]) -> OddsApiAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=events_response)

    client = OddsApiClient(api_key="test_key", transport=httpx.MockTransport(handler))
    registry = {
        "tbos_match_1": OddsApiEventRef(
            sport_key="tennis_atp_wimbledon", event_id="evt1",
            player_a_name="Player A", player_b_name="Player B",
        )
    }
    return OddsApiAdapter(client, registry)


def test_maps_h2h_event_to_two_quotes_per_book() -> None:
    adapter = _adapter([EVENT_JSON])
    quotes = adapter.fetch_odds("tbos_match_1", InstrumentType.MONEYLINE)

    assert len(quotes) == 2
    by_selection = {q.selection: q for q in quotes}
    assert by_selection["player_a"].odds == 1.9
    assert by_selection["player_b"].odds == 2.0
    assert all(q.book_id == "pinnacle" for q in quotes)
    assert all(q.match_id == "tbos_match_1" for q in quotes)
    assert all(q.instrument_type == InstrumentType.MONEYLINE for q in quotes)


def test_unregistered_match_id_raises_entity_not_found() -> None:
    adapter = _adapter([EVENT_JSON])
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_odds("unknown_match", InstrumentType.MONEYLINE)


def test_non_moneyline_instrument_raises_entity_not_found() -> None:
    adapter = _adapter([EVENT_JSON])
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_odds("tbos_match_1", InstrumentType.HANDICAP)


def test_event_id_not_in_response_raises_entity_not_found() -> None:
    adapter = _adapter([])  # API returns no events at all
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_odds("tbos_match_1", InstrumentType.MONEYLINE)


def test_multiple_bookmakers_each_produce_two_quotes() -> None:
    second_book = {**EVENT_JSON["bookmakers"][0], "key": "betfair", "title": "Betfair"}
    event = {**EVENT_JSON, "bookmakers": [EVENT_JSON["bookmakers"][0], second_book]}
    adapter = _adapter([event])
    quotes = adapter.fetch_odds("tbos_match_1", InstrumentType.MONEYLINE)
    assert len(quotes) == 4
    assert {q.book_id for q in quotes} == {"pinnacle", "betfair"}


def test_unrecognized_outcome_name_is_skipped_not_fabricated() -> None:
    event = {
        **EVENT_JSON,
        "bookmakers": [
            {
                "key": "pinnacle",
                "last_update": "2026-07-14T10:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": "2026-07-14T10:00:00Z",
                        "outcomes": [
                            {"name": "Player A", "price": 1.9},
                            {"name": "Some Draw Outcome", "price": 15.0},
                        ],
                    }
                ],
            }
        ],
    }
    adapter = _adapter([event])
    quotes = adapter.fetch_odds("tbos_match_1", InstrumentType.MONEYLINE)
    assert len(quotes) == 1
    assert quotes[0].selection == "player_a"


def test_non_h2h_market_ignored() -> None:
    event = {
        **EVENT_JSON,
        "bookmakers": [
            {
                "key": "pinnacle",
                "last_update": "2026-07-14T10:00:00Z",
                "markets": [
                    {"key": "totals", "last_update": "2026-07-14T10:00:00Z", "outcomes": []}
                ],
            }
        ],
    }
    adapter = _adapter([event])
    quotes = adapter.fetch_odds("tbos_match_1", InstrumentType.MONEYLINE)
    assert quotes == []


def test_malformed_bookmaker_raises_source_unavailable() -> None:
    event = {**EVENT_JSON, "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h"}]}]}  # missing "outcomes"
    adapter = _adapter([event])
    with pytest.raises(SourceUnavailableError):
        adapter.fetch_odds("tbos_match_1", InstrumentType.MONEYLINE)
