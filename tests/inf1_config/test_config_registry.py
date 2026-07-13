import pytest
from sqlalchemy.orm import Session

from tbos.inf1_config import repository
from tbos.inf1_config.models import ImmutableRecordError
from tbos.inf1_config.schemas import BankrollConfig, ConfigVersionBundle, RiskConfig


def _bundle(capital: float = 10_000.0) -> ConfigVersionBundle:
    return ConfigVersionBundle(
        bankroll=BankrollConfig(total_capital=capital),
        risk=RiskConfig(aggressiveness_threshold=0.5),
    )


def test_publish_config_version_creates_new_immutable_row(session: Session) -> None:
    row = repository.publish_config_version(session, _bundle(), approved_by="alice")
    session.commit()

    fetched = repository.get_config_version(session, row.config_version_id)
    assert fetched is not None
    assert fetched.bundle["bankroll"]["total_capital"] == 10_000.0
    assert fetched.approved_by == "alice"


def test_publishing_twice_creates_two_distinct_versions_never_overwrites(session: Session) -> None:
    first = repository.publish_config_version(session, _bundle(10_000), approved_by="alice")
    second = repository.publish_config_version(session, _bundle(20_000), approved_by="bob")
    session.commit()

    assert first.config_version_id != second.config_version_id
    assert repository.get_config_version(session, first.config_version_id).bundle["bankroll"][
        "total_capital"
    ] == 10_000.0
    assert repository.get_latest_config_version(session).config_version_id == second.config_version_id


def test_config_version_is_immutable_update_raises(session: Session) -> None:
    row = repository.publish_config_version(session, _bundle(), approved_by="alice")
    session.commit()

    row.approved_by = "mallory"
    with pytest.raises(ImmutableRecordError):
        session.commit()
