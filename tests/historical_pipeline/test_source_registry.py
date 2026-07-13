from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tbos.historical_pipeline import source_registry


def test_register_and_get_source(session: Session) -> None:
    source_registry.register_source(
        session,
        source_id="atp_stats_provider",
        domain="PLAYER_STATS",
        coverage_start=datetime(2015, 1, 1, tzinfo=timezone.utc),
        coverage_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
        format="json",
        reliability_prior=0.9,
    )
    session.commit()

    fetched = source_registry.get_source(session, "atp_stats_provider")
    assert fetched is not None
    assert fetched.domain == "PLAYER_STATS"
    assert fetched.reliability_prior == 0.9


def test_get_unknown_source_returns_none(session: Session) -> None:
    assert source_registry.get_source(session, "nonexistent") is None
