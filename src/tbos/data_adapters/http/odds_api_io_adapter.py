"""OddsSourceAdapter implementation backed by odds-api.io, v1 scope:
Moneyline ("ML" market) only — same scope The Odds API adapter had.

Simpler than the OddsApiAdapter it replaces: odds-api.io's event ids are
globally unique and directly queryable (`GET /v3/odds?eventId=...`), so
there is no need for an OddsApiEventRef-style match_id -> (sport_key,
event) registry — match_id is just str(event_id).

Player names arrive as "Surname, Firstname" (e.g. "Borges, Nuno") — a
third format distinct from Sackmann's "First Last" and tennis-data.co.uk's
"Surname I.". This adapter does not resolve names itself (same
separation as before: name resolution is the caller's job, via
PlayerNameResolver) — it only transforms JSON into RawOddsQuote.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    OddsSourceAdapter,
    RawOddsQuote,
    SourceMetadata,
    SourceUnavailableError,
)
from tbos.data_adapters.http.odds_api_io_client import FREE_TIER_BOOKMAKERS, OddsApiIoClient
from tbos.inf1_config.taxonomy import InstrumentType

logger = logging.getLogger("tbos.data_adapters.odds_api_io")

PARSER_VERSION = "1.0.0"
MONEYLINE_MARKET_NAME = "ML"


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class OddsApiIoAdapter(OddsSourceAdapter):
    source_id = "odds_api_io"

    def __init__(
        self,
        client: OddsApiIoClient,
        *,
        sport: str = "tennis",
        bookmakers: tuple[str, ...] = FREE_TIER_BOOKMAKERS,
        source_trust_score: float = 0.7,
        source_priority_rank: int = 1,
    ) -> None:
        self._client = client
        self._sport = sport
        self._bookmakers = bookmakers
        self._source_trust_score = source_trust_score
        self._source_priority_rank = source_priority_rank

    def fetch_odds(self, match_id: str, instrument_type: InstrumentType) -> list[RawOddsQuote]:
        if instrument_type != InstrumentType.MONEYLINE:
            raise EntityNotFoundError(
                f"OddsApiIoAdapter only supports MONEYLINE in v1, got {instrument_type!r}"
            )

        event = self._client.get_odds(
            sport=self._sport, event_id=match_id, bookmakers=self._bookmakers,
        )

        try:
            return self._map_event_to_quotes(match_id, event)
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailableError(f"malformed response from odds-api.io: {exc}") from exc

    def _map_event_to_quotes(self, match_id: str, event: dict) -> list[RawOddsQuote]:
        collected_at = datetime.now(UTC)
        quotes: list[RawOddsQuote] = []

        bookmakers_data = event.get("bookmakers", {})
        for book_name, markets in bookmakers_data.items():
            for market in markets:
                if market.get("name") != MONEYLINE_MARKET_NAME:
                    continue
                captured_at = _parse_timestamp(market["updatedAt"])
                for odds_entry in market.get("odds", []):
                    home_price = odds_entry.get("home")
                    away_price = odds_entry.get("away")
                    if home_price is None or away_price is None:
                        # Some markets carry partial rows (e.g. only a
                        # lay price posted) — a moneyline quote missing
                        # either side is not usable, skip it rather than
                        # fabricate the other side.
                        continue

                    for selection, price in (("player_a", home_price), ("player_b", away_price)):
                        quotes.append(
                            RawOddsQuote(
                                match_id=match_id,
                                instrument_type=InstrumentType.MONEYLINE,
                                book_id=book_name,
                                selection=selection,
                                odds=float(price),
                                captured_at=captured_at,
                                metadata=SourceMetadata(
                                    source_id=self.source_id,
                                    collected_at=collected_at,
                                    parser_version=PARSER_VERSION,
                                    source_priority_rank=self._source_priority_rank,
                                    source_trust_score=self._source_trust_score,
                                ),
                            )
                        )

        return quotes
