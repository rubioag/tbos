import uuid
from datetime import datetime, timedelta, timezone

from tbos.inf1_config.taxonomy import MistakeCategory
from tbos.inf3_review.mistake_patterns import MistakeOccurrence, aggregate_mistake_patterns

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_aggregates_by_category_separately() -> None:
    occurrences = [
        MistakeOccurrence(bet_id=uuid.uuid4(), category=MistakeCategory.MODEL_ERROR, occurred_at=NOW, description="x"),
        MistakeOccurrence(bet_id=uuid.uuid4(), category=MistakeCategory.MODEL_ERROR, occurred_at=NOW, description="y"),
        MistakeOccurrence(bet_id=uuid.uuid4(), category=MistakeCategory.EXECUTION_ERROR, occurred_at=NOW, description="z"),
    ]
    records = aggregate_mistake_patterns(occurrences, min_sample_size_for_full_confidence=10, now=NOW)
    by_cat = {r.category: r for r in records}
    assert by_cat[MistakeCategory.MODEL_ERROR].recurrence_count == 2
    assert by_cat[MistakeCategory.EXECUTION_ERROR].recurrence_count == 1


def test_recency_score_decays_for_old_occurrences() -> None:
    recent = [MistakeOccurrence(bet_id=uuid.uuid4(), category=MistakeCategory.MARKET_MISREAD, occurred_at=NOW, description="x")]
    old = [
        MistakeOccurrence(
            bet_id=uuid.uuid4(),
            category=MistakeCategory.MARKET_MISREAD,
            occurred_at=NOW - timedelta(days=90),
            description="x",
        )
    ]

    recent_record = aggregate_mistake_patterns(recent, min_sample_size_for_full_confidence=10, now=NOW)[0]
    old_record = aggregate_mistake_patterns(old, min_sample_size_for_full_confidence=10, now=NOW)[0]

    assert recent_record.finding_confidence.recency_score > old_record.finding_confidence.recency_score


def test_version_consistency_drops_when_occurrences_span_multiple_versions() -> None:
    single_version = [
        MistakeOccurrence(
            bet_id=uuid.uuid4(), category=MistakeCategory.BEHAVIORAL_ERROR, occurred_at=NOW,
            description="x", engine_or_model_version="1.0.0",
        ),
        MistakeOccurrence(
            bet_id=uuid.uuid4(), category=MistakeCategory.BEHAVIORAL_ERROR, occurred_at=NOW,
            description="y", engine_or_model_version="1.0.0",
        ),
    ]
    mixed_versions = [
        MistakeOccurrence(
            bet_id=uuid.uuid4(), category=MistakeCategory.BEHAVIORAL_ERROR, occurred_at=NOW,
            description="x", engine_or_model_version="1.0.0",
        ),
        MistakeOccurrence(
            bet_id=uuid.uuid4(), category=MistakeCategory.BEHAVIORAL_ERROR, occurred_at=NOW,
            description="y", engine_or_model_version="2.0.0",
        ),
    ]

    consistent = aggregate_mistake_patterns(single_version, min_sample_size_for_full_confidence=10, now=NOW)[0]
    inconsistent = aggregate_mistake_patterns(mixed_versions, min_sample_size_for_full_confidence=10, now=NOW)[0]

    assert consistent.finding_confidence.version_consistency_score == 1.0
    assert inconsistent.finding_confidence.version_consistency_score == 0.5
    assert inconsistent.finding_confidence.composite < consistent.finding_confidence.composite


def test_time_window_spans_first_to_last_occurrence() -> None:
    occurrences = [
        MistakeOccurrence(bet_id=uuid.uuid4(), category=MistakeCategory.UNKNOWN_UNKNOWN, occurred_at=NOW, description="x"),
        MistakeOccurrence(
            bet_id=uuid.uuid4(), category=MistakeCategory.UNKNOWN_UNKNOWN,
            occurred_at=NOW + timedelta(days=5), description="y",
        ),
    ]
    record = aggregate_mistake_patterns(occurrences, min_sample_size_for_full_confidence=10, now=NOW + timedelta(days=5))[0]
    assert record.time_window_start == NOW
    assert record.time_window_end == NOW + timedelta(days=5)


def test_empty_occurrences_yields_no_records() -> None:
    assert aggregate_mistake_patterns([], min_sample_size_for_full_confidence=10, now=NOW) == []
