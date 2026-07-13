"""Historical Data Pipeline §E — Data Quality Validation. Gaps and
conflicts are reported honestly, never silently interpolated — same
principle CE.1 applies to live data, applied here to historical batches.
"""

from __future__ import annotations

from pydantic import BaseModel

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.inf1_config.taxonomy import FieldAvailability


class HistoricalDataQualityReport(BaseModel):
    source_id: str
    total_fields: int
    missing_count: int
    conflict_count: int
    gap_rate: float
    conflict_rate: float


def compute_quality_report(source_id: str, envelopes: list[FieldEnvelope]) -> HistoricalDataQualityReport:
    total = len(envelopes)
    missing = sum(1 for e in envelopes if e.availability == FieldAvailability.MISSING)
    conflicts = sum(1 for e in envelopes if e.has_conflict)
    return HistoricalDataQualityReport(
        source_id=source_id,
        total_fields=total,
        missing_count=missing,
        conflict_count=conflicts,
        gap_rate=(missing / total) if total else 0.0,
        conflict_rate=(conflicts / total) if total else 0.0,
    )
