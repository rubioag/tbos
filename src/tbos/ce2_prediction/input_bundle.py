"""CE.2.1 — ModelInputBundle: the only thing a Model is ever handed.

Loaded once per match evaluation from CE.1 snapshots (live via
get_latest_snapshot, or historical via get_snapshot_as_of — the loader
takes an explicit `as_of` so both paths share one code path and
backtesting/live never silently diverge). IL.2 Knowledge entries are not
wired yet (IL.2 doesn't exist) — `optional_fields` resolution against it
is deferred, same graceful-degradation pattern used throughout the build.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import MatchContext, PlayerProfile, PlayerState


class ModelInputBundle(BaseModel):
    match_id: str
    player_a_id: str
    player_b_id: str

    # The evaluation instant this bundle represents. Models must use this,
    # never datetime.now(), for anything timestamp-related in their output
    # (Common Model Contract §10 — no clock reads beyond what's in the bundle).
    as_of: datetime

    player_a_profile: PlayerProfile | None = None
    player_a_state: PlayerState | None = None
    player_b_profile: PlayerProfile | None = None
    player_b_state: PlayerState | None = None
    match_context: MatchContext | None = None

    # entity_key -> snapshot_id, for contribution lineage / version stamping
    snapshot_refs: dict[str, uuid.UUID] = {}


_ENTITY_MAP = {
    "player_a_profile": ("PlayerProfile", "player_a_id"),
    "player_a_state": ("PlayerState", "player_a_id"),
    "player_b_profile": ("PlayerProfile", "player_b_id"),
    "player_b_state": ("PlayerState", "player_b_id"),
    "match_context": ("MatchContext", "match_id"),
}


def load_input_bundle(
    session: Session, *, match_id: str, player_a_id: str, player_b_id: str, as_of: datetime
) -> ModelInputBundle:
    ids = {"player_a_id": player_a_id, "player_b_id": player_b_id, "match_id": match_id}
    bundle_kwargs: dict[str, object] = {
        "match_id": match_id, "player_a_id": player_a_id, "player_b_id": player_b_id, "as_of": as_of
    }
    snapshot_refs: dict[str, uuid.UUID] = {}

    schema_by_entity_type = {"PlayerProfile": PlayerProfile, "PlayerState": PlayerState, "MatchContext": MatchContext}

    for field_name, (entity_type, id_key) in _ENTITY_MAP.items():
        entity_id = ids[id_key]
        snapshot = ce1_repository.get_snapshot_as_of(session, entity_type, entity_id, as_of)
        if snapshot is None:
            continue
        schema = schema_by_entity_type[entity_type]
        bundle_kwargs[field_name] = schema.model_validate(snapshot.fields)
        snapshot_refs[field_name] = snapshot.snapshot_id

    bundle_kwargs["snapshot_refs"] = snapshot_refs
    return ModelInputBundle.model_validate(bundle_kwargs)


def resolve_field_path(bundle: ModelInputBundle, path: str) -> FieldEnvelope | None:
    """`path` is dotted, e.g. "player_a_profile.first_serve_pct_by_surface".
    Returns None if any segment along the way is missing entirely (the
    parent entity snapshot didn't exist) — distinct from a FieldEnvelope
    that exists but is itself MISSING/INVALID.
    """
    parts = path.split(".")
    obj: object = bundle
    for part in parts:
        if obj is None:
            return None
        obj = getattr(obj, part, None)
    return obj if isinstance(obj, FieldEnvelope) else None


def check_required_fields(bundle: ModelInputBundle, required_fields: list[str]) -> tuple[bool, list[str]]:
    """A required field only satisfies the Model's contract if it resolves
    AND is usable (present + valid) — stale-but-present still counts as
    satisfied (staleness is an Evidence Quality signal, not an abstention
    trigger on its own).
    """
    missing: list[str] = []
    for path in required_fields:
        envelope = resolve_field_path(bundle, path)
        if envelope is None or not envelope.is_usable():
            missing.append(path)
    return (len(missing) == 0, missing)
