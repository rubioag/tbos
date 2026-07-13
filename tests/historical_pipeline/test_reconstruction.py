from datetime import datetime, timedelta, timezone

from tbos.ce1_data.pipeline import RawFieldCandidate
from tbos.historical_pipeline.reconstruction import build_historical_field
from tbos.inf1_config.taxonomy import FieldAvailability

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _candidate(collected_at: datetime, value: float = 0.65) -> RawFieldCandidate:
    return RawFieldCandidate(
        value=value,
        source_id="atp_stats_provider",
        collected_at=collected_at,
        parser_version="1.0.0",
        source_priority_rank=1,
        source_trust_score=0.9,
    )


def test_candidate_collected_before_as_of_is_usable() -> None:
    env = build_historical_field(_candidate(AS_OF - timedelta(days=1)), as_of=AS_OF)
    assert env.is_usable()
    assert env.value == 0.65


def test_candidate_collected_exactly_at_as_of_is_usable() -> None:
    env = build_historical_field(_candidate(AS_OF), as_of=AS_OF)
    assert env.is_usable()


def test_candidate_collected_after_as_of_is_forced_missing_even_though_value_exists() -> None:
    """The core anti-lookahead guarantee: knowing the future answer must
    never leak into a historical reconstruction.
    """
    env = build_historical_field(_candidate(AS_OF + timedelta(days=1)), as_of=AS_OF)
    assert env.availability == FieldAvailability.MISSING
    assert env.value is None
    assert not env.is_usable()
    assert "not knowable as of" in env.lineage[0].detail


def test_no_candidate_is_missing() -> None:
    env = build_historical_field(None, as_of=AS_OF)
    assert env.availability == FieldAvailability.MISSING
