from datetime import datetime, timedelta, timezone

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.pipeline import (
    RawFieldCandidate,
    build_field_envelope,
    detect_conflict,
    merge_research_update,
)
from tbos.inf1_config.taxonomy import FieldAvailability, FieldValidity, FreshnessStatus, InformationReliability

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _candidate(**overrides: object) -> RawFieldCandidate:
    defaults = dict(
        value=0.65,
        source_id="atp_stats_provider",
        collected_at=NOW - timedelta(seconds=10),
        parser_version="1.0.0",
        source_priority_rank=1,
        source_trust_score=0.9,
    )
    defaults.update(overrides)
    return RawFieldCandidate(**defaults)  # type: ignore[arg-type]


def test_build_envelope_from_valid_candidate() -> None:
    env = build_field_envelope(
        _candidate(), validate=lambda v: 0.0 <= v <= 1.0, freshness_threshold_seconds=60, now=NOW
    )
    assert env.is_usable()
    assert env.value == 0.65
    assert env.freshness.status == FreshnessStatus.FRESH
    assert env.provenance.source_id == "atp_stats_provider"
    assert env.taxonomy_tag == InformationReliability.FACT
    stages = [step.stage for step in env.lineage]
    assert stages == ["RawSource", "Validation", "Normalization", "PublishedRecord"]


def test_build_envelope_no_candidate_is_missing() -> None:
    env = build_field_envelope(None, validate=lambda v: True, freshness_threshold_seconds=60, now=NOW)
    assert env.availability == FieldAvailability.MISSING
    assert not env.is_usable()


def test_build_envelope_out_of_range_is_invalid_never_published_as_valid() -> None:
    env = build_field_envelope(
        _candidate(value=42.0),  # nonsensical for a 0-1 pct field
        validate=lambda v: 0.0 <= v <= 1.0,
        freshness_threshold_seconds=60,
        now=NOW,
    )
    assert env.validity == FieldValidity.INVALID
    assert env.value is None  # rejected, never published as if valid
    assert not env.is_usable()


def test_build_envelope_stale_data_still_usable_but_flagged() -> None:
    env = build_field_envelope(
        _candidate(collected_at=NOW - timedelta(hours=2)),
        validate=lambda v: True,
        freshness_threshold_seconds=60,
        now=NOW,
    )
    assert env.freshness.status == FreshnessStatus.STALE
    assert env.is_usable()  # stale != invalid — CE.1 §9, downstream decides weight


def test_build_envelope_future_dated_rejected() -> None:
    env = build_field_envelope(
        _candidate(collected_at=NOW + timedelta(hours=1)),
        validate=lambda v: True,
        freshness_threshold_seconds=60,
        now=NOW,
    )
    assert env.validity == FieldValidity.INVALID


def test_conflict_detected_and_both_candidates_preserved() -> None:
    a = build_field_envelope(
        _candidate(value=0.60, source_id="provider_a", source_priority_rank=1),
        validate=lambda v: True,
        freshness_threshold_seconds=3600,
        now=NOW,
    )
    b = build_field_envelope(
        _candidate(value=0.70, source_id="provider_b", source_priority_rank=2),
        validate=lambda v: True,
        freshness_threshold_seconds=3600,
        now=NOW,
    )
    result = detect_conflict([a, b])
    assert result.has_conflict is True
    assert result.value == 0.60  # highest-priority (lowest rank number) source wins as primary
    assert len(result.conflicting_candidates) == 2


def test_no_conflict_when_sources_agree() -> None:
    a = build_field_envelope(
        _candidate(value=0.60, source_id="provider_a"),
        validate=lambda v: True,
        freshness_threshold_seconds=3600,
        now=NOW,
    )
    b = build_field_envelope(
        _candidate(value=0.60, source_id="provider_b"),
        validate=lambda v: True,
        freshness_threshold_seconds=3600,
        now=NOW,
    )
    result = detect_conflict([a, b])
    assert result.has_conflict is False


def test_research_merge_never_overwrites_fact() -> None:
    fact = build_field_envelope(
        _candidate(value=0.65, taxonomy_tag=InformationReliability.FACT),
        validate=lambda v: True,
        freshness_threshold_seconds=3600,
        now=NOW,
    )
    rumor = build_field_envelope(
        _candidate(value=0.10, taxonomy_tag=InformationReliability.HYPOTHESIS, source_id="press_conference"),
        validate=lambda v: True,
        freshness_threshold_seconds=3600,
        now=NOW,
    )
    merged = merge_research_update(fact, rumor, changed_by="il1_research_synthesis", reason="injury rumor")
    assert merged is fact
    assert merged.value == 0.65


def test_research_merge_updates_hypothesis_and_records_history() -> None:
    existing = build_field_envelope(
        _candidate(value=0.0, taxonomy_tag=InformationReliability.HYPOTHESIS),
        validate=lambda v: True,
        freshness_threshold_seconds=3600,
        now=NOW,
    )
    update = build_field_envelope(
        _candidate(value=1.0, taxonomy_tag=InformationReliability.HYPOTHESIS, source_id="press_conference"),
        validate=lambda v: True,
        freshness_threshold_seconds=3600,
        now=NOW,
    )
    merged = merge_research_update(existing, update, changed_by="il1_research_synthesis", reason="new report")
    assert merged.value == 1.0
    assert len(merged.modification_history) == 1
    assert merged.modification_history[0].prior_value == 0.0
    assert any(step.stage == "ResearchMerge" for step in merged.lineage)
