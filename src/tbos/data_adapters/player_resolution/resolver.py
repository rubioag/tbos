"""Resolves an external provider's player name (e.g. The Odds API's
"Felix Auger-Aliassime") to a Sackmann player_id, deterministically and
conservatively. Reuses the existing, frozen EntityNotFoundError contract
for abstention — this is not a new error type, it's the same "the source
has no record for this entity" signal the rest of TBOS already handles.

Resolution tiers, in order:
1. Exact match after normalization — confidence 1.0. Covers the large
   majority of real cases (accents, hyphens, punctuation, case).
2. Reversed word order (handles "Last First" inputs) — confidence 0.95,
   only if it resolves to exactly one player_id.
3. Fuzzy match (difflib ratio) — only accepted if the best candidate's
   ratio clears `fuzzy_threshold` AND resolves to exactly one player_id.
   Every fuzzy acceptance is recorded with its actual confidence value;
   there is no path that accepts a fuzzy match without logging it.

At every tier, ambiguity (more than one player_id sharing the same
normalized name) is treated as abstention, never a guess — two different
real players can plausibly share a normalized name across eras/tours.
"""

from __future__ import annotations

import difflib
from datetime import UTC, datetime

from tbos.data_adapters.contracts import EntityNotFoundError
from tbos.data_adapters.player_resolution.normalize import normalize_player_name
from tbos.data_adapters.player_resolution.store import PlayerNameMappingStore, PlayerNameResolution
from tbos.data_adapters.sackmann.models import MatchRow

DEFAULT_FUZZY_THRESHOLD = 0.90


class PlayerNameResolver:
    def __init__(
        self,
        matches: list[MatchRow],
        store: PlayerNameMappingStore,
        *,
        source: str = "the_odds_api",
        fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    ) -> None:
        self._store = store
        self._source = source
        self._fuzzy_threshold = fuzzy_threshold
        self._index: dict[str, set[str]] = {}
        for match in matches:
            if match.winner_name:
                key = normalize_player_name(match.winner_name)
                self._index.setdefault(key, set()).add(match.winner_id)
            if match.loser_name:
                key = normalize_player_name(match.loser_name)
                self._index.setdefault(key, set()).add(match.loser_id)

    def resolve(self, source_name: str, *, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)

        cached = self._store.get(self._source, source_name)
        if cached is not None:
            return cached.player_id

        normalized = normalize_player_name(source_name)

        exact = self._index.get(normalized)
        if exact is not None:
            if len(exact) > 1:
                raise EntityNotFoundError(
                    f"ambiguous name {source_name!r}: {len(exact)} distinct player_ids share "
                    f"normalized form {normalized!r} — abstaining, not guessing"
                )
            player_id = next(iter(exact))
            self._record(
                source_name, normalized, player_id, confidence=1.0, method="exact", now=now,
            )
            return player_id

        reversed_candidate = self._try_reversed_order(normalized)
        if reversed_candidate is not None:
            player_id = reversed_candidate
            self._record(
                source_name, normalized, player_id,
                confidence=0.95, method="reversed_order", now=now,
            )
            return player_id

        best_name, best_ratio, best_ids = self._best_fuzzy_candidate(normalized)
        if best_ratio >= self._fuzzy_threshold and best_ids is not None and len(best_ids) == 1:
            player_id = next(iter(best_ids))
            self._record(
                source_name, normalized, player_id,
                confidence=best_ratio, method="fuzzy", now=now,
            )
            return player_id

        raise EntityNotFoundError(
            f"could not resolve player name {source_name!r} to a Sackmann player_id "
            f"(best candidate {best_name!r}, confidence {best_ratio:.3f}, "
            f"threshold {self._fuzzy_threshold}) — abstaining, never guessing"
        )

    def _try_reversed_order(self, normalized: str) -> str | None:
        tokens = normalized.split(" ")
        if len(tokens) < 2:
            return None
        reversed_normalized = " ".join(tokens[::-1])
        candidates = self._index.get(reversed_normalized)
        if candidates is not None and len(candidates) == 1:
            return next(iter(candidates))
        return None

    def _best_fuzzy_candidate(self, normalized: str) -> tuple[str | None, float, set[str] | None]:
        best_name: str | None = None
        best_ratio = 0.0
        best_ids: set[str] | None = None
        for candidate_name, ids in self._index.items():
            ratio = difflib.SequenceMatcher(None, normalized, candidate_name).ratio()
            if ratio > best_ratio:
                best_ratio, best_name, best_ids = ratio, candidate_name, ids
        return best_name, best_ratio, best_ids

    def _record(
        self, source_name: str, normalized_name: str, player_id: str, *,
        confidence: float, method: str, now: datetime,
    ) -> None:
        self._store.append(
            PlayerNameResolution(
                source=self._source, source_name=source_name, normalized_name=normalized_name,
                player_id=player_id, confidence=confidence, method=method, resolved_at=now,
            )
        )
