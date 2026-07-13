import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from tbos.ce1_data import repository
from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.models import Snapshot as SnapshotTable
from tbos.ce1_data.schemas import PlayerProfile
from tbos.common import ImmutableRecordError
from tbos.inf1_config.taxonomy import FieldAvailability, FieldValidity, InformationReliability

CONFIG_VERSION_ID = uuid.uuid4()


def _sample_profile(ranking: int = 5) -> PlayerProfile:
    def env(value: object) -> FieldEnvelope:
        return FieldEnvelope(
            value=value,
            availability=FieldAvailability.PRESENT,
            validity=FieldValidity.VALID,
            taxonomy_tag=InformationReliability.FACT,
        )

    return PlayerProfile(
        player_id=env("player_123"),
        ranking=env(ranking),
        first_serve_pct_by_surface=env({"HARD": 0.62}),
        service_points_won_pct_by_surface=env({"HARD": 0.71}),
        aces_per_match_by_surface=env({"HARD": 8.2}),
        hold_rate_by_surface=env({"HARD": 0.85}),
        return_points_won_pct_by_surface=env({"HARD": 0.38}),
        break_points_converted_pct_by_surface=env({"HARD": 0.41}),
        style_tags=env(["baseline", "two-handed-backhand"]),
        career_stage=env("PEAK"),
        h2h_records=env([]),
    )


def test_publish_and_retrieve_snapshot(session: Session) -> None:
    row = repository.publish_snapshot(
        session,
        entity_type="PlayerProfile",
        entity_id="player_123",
        fields=_sample_profile(),
        config_version_id=CONFIG_VERSION_ID,
    )
    session.commit()

    fetched = repository.get_snapshot(session, row.snapshot_id)
    assert fetched is not None
    assert fetched.fields["ranking"]["value"] == 5
    assert fetched.fields["ranking"]["taxonomy_tag"] == "FACT"


def test_snapshot_is_immutable(session: Session) -> None:
    row = repository.publish_snapshot(
        session,
        entity_type="PlayerProfile",
        entity_id="player_123",
        fields=_sample_profile(),
        config_version_id=CONFIG_VERSION_ID,
    )
    session.commit()

    row.entity_id = "tampered"
    with pytest.raises(ImmutableRecordError):
        session.commit()


def test_correction_creates_new_snapshot_never_mutates_original(session: Session) -> None:
    original = repository.publish_snapshot(
        session,
        entity_type="PlayerProfile",
        entity_id="player_123",
        fields=_sample_profile(ranking=5),
        config_version_id=CONFIG_VERSION_ID,
    )
    session.commit()

    corrected = repository.publish_snapshot(
        session,
        entity_type="PlayerProfile",
        entity_id="player_123",
        fields=_sample_profile(ranking=4),
        config_version_id=CONFIG_VERSION_ID,
        supersedes=original.snapshot_id,
    )
    session.commit()

    assert repository.get_snapshot(session, original.snapshot_id).fields["ranking"]["value"] == 5
    assert corrected.supersedes == original.snapshot_id

    lineage = repository.get_snapshot_lineage(session, corrected.snapshot_id)
    assert [s.snapshot_id for s in lineage] == [original.snapshot_id, corrected.snapshot_id]


def test_get_latest_snapshot_returns_most_recent(session: Session) -> None:
    repository.publish_snapshot(
        session,
        entity_type="PlayerProfile",
        entity_id="player_123",
        fields=_sample_profile(ranking=5),
        config_version_id=CONFIG_VERSION_ID,
    )
    second = repository.publish_snapshot(
        session,
        entity_type="PlayerProfile",
        entity_id="player_123",
        fields=_sample_profile(ranking=4),
        config_version_id=CONFIG_VERSION_ID,
    )
    session.commit()

    latest = repository.get_latest_snapshot(session, "PlayerProfile", "player_123")
    assert latest.snapshot_id == second.snapshot_id


def test_get_snapshot_as_of_never_returns_future_snapshot(session: Session) -> None:
    """Anti-lookahead guarantee (Historical Data Pipeline §B): a query
    as_of=t1 must never see a snapshot published after t1.
    """
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = t1 + timedelta(days=1)

    old = repository.publish_snapshot(
        session,
        entity_type="PlayerProfile",
        entity_id="player_123",
        fields=_sample_profile(ranking=5),
        config_version_id=CONFIG_VERSION_ID,
    )
    session.commit()
    # Simulate the row's published_at as if it happened at t1. Uses a
    # Core-level bulk update (proper DateTime type coercion, unlike raw
    # text SQL) which also intentionally bypasses the ORM before_update
    # mapper event — this is a test-only backdoor to construct fixtures;
    # production code has no path that does this.
    session.execute(sa.update(SnapshotTable).where(SnapshotTable.id == old.id).values(published_at=t1))
    session.commit()

    new = repository.publish_snapshot(
        session,
        entity_type="PlayerProfile",
        entity_id="player_123",
        fields=_sample_profile(ranking=4),
        config_version_id=CONFIG_VERSION_ID,
        supersedes=old.snapshot_id,
    )
    session.commit()
    session.execute(sa.update(SnapshotTable).where(SnapshotTable.id == new.id).values(published_at=t2))
    session.commit()

    as_of_t1 = repository.get_snapshot_as_of(session, "PlayerProfile", "player_123", t1 + timedelta(hours=1))
    assert as_of_t1.snapshot_id == old.snapshot_id

    as_of_before_anything = repository.get_snapshot_as_of(
        session, "PlayerProfile", "player_123", t1 - timedelta(days=1)
    )
    assert as_of_before_anything is None
