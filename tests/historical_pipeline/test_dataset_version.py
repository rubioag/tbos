import uuid

import pytest
from sqlalchemy.orm import Session

from tbos.common import ImmutableRecordError
from tbos.historical_pipeline import dataset_version


def test_publish_and_get_dataset_version(session: Session) -> None:
    config_version_id = uuid.uuid4()
    row = dataset_version.publish_dataset_version(
        session, source_versions={"atp_stats": "2026.01"}, config_version_id=config_version_id
    )
    session.commit()

    fetched = dataset_version.get_dataset_version(session, row.dataset_version_id)
    assert fetched is not None
    assert fetched.source_versions["atp_stats"] == "2026.01"


def test_latest_dataset_version_returns_most_recent(session: Session) -> None:
    dataset_version.publish_dataset_version(session, source_versions={"a": "1"}, config_version_id=uuid.uuid4())
    second = dataset_version.publish_dataset_version(session, source_versions={"a": "2"}, config_version_id=uuid.uuid4())
    session.commit()

    latest = dataset_version.get_latest_dataset_version(session)
    assert latest.dataset_version_id == second.dataset_version_id


def test_dataset_version_is_immutable(session: Session) -> None:
    row = dataset_version.publish_dataset_version(
        session, source_versions={"a": "1"}, config_version_id=uuid.uuid4()
    )
    session.commit()

    row.source_versions = {"a": "tampered"}
    with pytest.raises(ImmutableRecordError):
        session.commit()
