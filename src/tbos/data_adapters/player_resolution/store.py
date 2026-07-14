"""Append-only persistent store for resolved (source_name -> player_id)
mappings — JSONL, one record per line, never rewritten or edited in
place. Mirrors TBOS's event-sourcing discipline (INF.2): a resolution,
once recorded, is a permanent fact with its own evidence (confidence,
method, timestamp), not a mutable cache entry that can silently change
underneath the system.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class PlayerNameResolution(BaseModel):
    source: str
    source_name: str
    normalized_name: str
    player_id: str
    confidence: float
    method: str  # "exact" | "reversed_order" | "fuzzy"
    resolved_at: datetime


class PlayerNameMappingStore:
    """Points at a single JSONL file. Loads existing records into memory
    once; `append()` writes through to disk immediately (durable) and
    updates the in-memory index.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._index: dict[tuple[str, str], PlayerNameResolution] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = PlayerNameResolution.model_validate_json(line)
                # First record for a given key wins — later duplicate
                # appends (should not normally happen) are evidence of a
                # bug elsewhere, not a reason to silently overwrite an
                # already-published resolution.
                key = (record.source, record.source_name)
                if key not in self._index:
                    self._index[key] = record

    def get(self, source: str, source_name: str) -> PlayerNameResolution | None:
        return self._index.get((source, source_name))

    def append(self, resolution: PlayerNameResolution) -> None:
        key = (resolution.source, resolution.source_name)
        if key in self._index:
            return  # already recorded — append-only, never duplicate/overwrite
        with self._path.open("a", encoding="utf-8") as f:
            f.write(resolution.model_dump_json() + "\n")
        self._index[key] = resolution
