from datetime import datetime, timedelta, timezone

from tbos.ce1_data.envelope import FieldEnvelope, compute_freshness, is_future_dated
from tbos.inf1_config.taxonomy import FieldAvailability, FieldValidity, FreshnessStatus, InformationReliability


def test_missing_envelope_is_never_bare_none() -> None:
    env = FieldEnvelope[str].missing(reason="source down")
    assert env.value is None
    assert env.availability == FieldAvailability.MISSING
    assert env.validity == FieldValidity.INVALID
    assert not env.is_usable()
    assert env.lineage[0].detail == "source down"


def test_present_and_valid_is_usable() -> None:
    env = FieldEnvelope[int](
        value=42,
        availability=FieldAvailability.PRESENT,
        validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
    )
    assert env.is_usable()


def test_present_but_invalid_is_not_usable() -> None:
    env = FieldEnvelope[int](
        value=None,
        availability=FieldAvailability.PRESENT,
        validity=FieldValidity.INVALID,
        taxonomy_tag=InformationReliability.FACT,
    )
    assert not env.is_usable()


def test_freshness_within_threshold_is_fresh() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    collected = now - timedelta(seconds=30)
    info = compute_freshness(collected, threshold_seconds=60, now=now)
    assert info.status == FreshnessStatus.FRESH
    assert info.age_seconds == 30


def test_freshness_beyond_threshold_is_stale() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    collected = now - timedelta(seconds=120)
    info = compute_freshness(collected, threshold_seconds=60, now=now)
    assert info.status == FreshnessStatus.STALE


def test_future_dated_detected() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert is_future_dated(now + timedelta(hours=1), now=now)
    assert not is_future_dated(now - timedelta(hours=1), now=now)


def test_envelope_round_trips_through_json() -> None:
    """Contract requirement: CE.2 Models consume this over the wire/DB —
    it must survive a JSON round trip losslessly.
    """
    env = FieldEnvelope[float](
        value=0.62,
        availability=FieldAvailability.PRESENT,
        validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
    )
    restored = FieldEnvelope[float].model_validate_json(env.model_dump_json())
    assert restored == env
