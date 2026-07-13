from tbos.ce1_data.envelope import FieldEnvelope
from tbos.historical_pipeline.quality import compute_quality_report
from tbos.inf1_config.taxonomy import FieldAvailability, FieldValidity, InformationReliability


def _present(value: float = 1.0, has_conflict: bool = False) -> FieldEnvelope:
    return FieldEnvelope(
        value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT, has_conflict=has_conflict,
    )


def test_quality_report_empty_batch_has_zero_rates_no_division_error() -> None:
    report = compute_quality_report("source_a", [])
    assert report.total_fields == 0
    assert report.gap_rate == 0.0
    assert report.conflict_rate == 0.0


def test_quality_report_counts_missing_and_conflicts_separately() -> None:
    envelopes = [
        _present(),
        _present(),
        FieldEnvelope.missing(),
        _present(has_conflict=True),
    ]
    report = compute_quality_report("source_a", envelopes)
    assert report.total_fields == 4
    assert report.missing_count == 1
    assert report.conflict_count == 1
    assert report.gap_rate == 0.25
    assert report.conflict_rate == 0.25
