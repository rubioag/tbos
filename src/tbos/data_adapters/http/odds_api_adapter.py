"""OddsSourceAdapter implementation backed by The Odds API
(https://the-odds-api.com/), v1 scope: Moneyline (h2h market) only.

TBOS match_id values are internal; The Odds API has no concept of them.
The mapping from match_id -> (sport_key, event_id, player names) is
business/operational knowledge the caller must supply via
`OddsApiEventRef` — this adapter only transforms the resulting JSON into
RawOddsQuote, exactly as required. It does not guess or fuzzy-match
player names.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel

from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    OddsSourceAdapter,
    RawOddsQuote,
    SourceMetadata,
    SourceUnavailableError,
)
from tbos.data_adapters.http.odds_api_client import OddsApiClient
from tbos.inf1_config.taxonomy import InstrumentType

logger = logging.getLogger("tbos.data_adapters.odds_api")

PARSER_VERSION = "1.0.0"


class OddsApiEventRef(BaseModel):
    """Caller-supplied mapping from a TBOS match_id to a The Odds API
    event. Player names must match the API's `home_team`/`away_team` (and
    h2h outcome `name`) values exactly.
    """

    sport_key: str
    event_id: str
    player_a_name: str
    player_b_name: str


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class OddsApiAdapter(OddsSourceAdapter):
    source_id = "the_odds_api"

    def __init__(
        self,
        client: OddsApiClient,
        event_registry: dict[str, OddsApiEventRef],
        *,
        source_trust_score: float = 0.9,
        source_priority_rank: int = 1,
    ) -> None:
        self._client = client
        self._event_registry = event_registry
        self._source_trust_score = source_trust_score
        self._source_priority_rank = source_priority_rank

    def fetch_odds(self, match_id: str, instrument_type: InstrumentType) -> list[RawOddsQuote]:
        if instrument_type != InstrumentType.MONEYLINE:
            raise EntityNotFoundError(
                f"OddsApiAdapter only supports MONEYLINE in v1, got {instrument_type!r}"
            )

        ref = self._event_registry.get(match_id)
        if ref is None:
            raise EntityNotFoundError(f"no The Odds API event registered for match_id={match_id!r}")

        events = self._client.get_odds(ref.sport_key, markets="h2h")

        event = next((e for e in events if e.get("id") == ref.event_id), None)
        if event is None:
            raise EntityNotFoundError(
                f"The Odds API returned no event with id={ref.event_id!r} "
                f"for sport_key={ref.sport_key!r}"
            )

        try:
            return self._map_event_to_quotes(match_id, event, ref)
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailableError(f"malformed response from The Odds API: {exc}") from exc

    def _map_event_to_quotes(
        self, match_id: str, event: dict, ref: OddsApiEventRef
    ) -> list[RawOddsQuote]:
        collected_at = datetime.now(UTC)
        quotes: list[RawOddsQuote] = []

        for bookmaker in event.get("bookmakers", []):
            book_id = bookmaker["key"]
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                raw_ts = market.get("last_update") or bookmaker["last_update"]
                captured_at = _parse_timestamp(raw_ts)
                for outcome in market["outcomes"]:
                    name = outcome["name"]
                    if name == ref.player_a_name:
                        selection = "player_a"
                    elif name == ref.player_b_name:
                        selection = "player_b"
                    else:
                        logger.warning(
                            "unrecognized outcome name in h2h market, skipped",
                            extra={"match_id": match_id, "book_id": book_id, "outcome_name": name},
                        )
                        continue

                    quotes.append(
                        RawOddsQuote(
                            match_id=match_id,
                            instrument_type=InstrumentType.MONEYLINE,
                            book_id=book_id,
                            selection=selection,
                            odds=float(outcome["price"]),
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
