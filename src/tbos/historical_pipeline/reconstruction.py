"""Historical Data Pipeline §B — anti-lookahead field reconstruction.

The single hard rule: a raw candidate collected AFTER `as_of` was not
knowable at that point in history and must be reported MISSING, even
though we may since have learned it. This is what makes a backtest
scenario honest rather than a system quietly cheating on its own history.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.pipeline import RawFieldCandidate, build_field_envelope


def build_historical_field(
    candidate: RawFieldCandidate | None,
    *,
    as_of: datetime,
    validate: Callable[[object], bool] = lambda v: True,
    freshness_threshold_seconds: float = float("inf"),
) -> FieldEnvelope:
    if candidate is not None and candidate.collected_at > as_of:
        return FieldEnvelope.missing(
            reason=(
                f"not knowable as of {as_of.isoformat()} "
                f"(source collected it {candidate.collected_at.isoformat()})"
            )
        )
    return build_field_envelope(
        candidate, validate=validate, freshness_threshold_seconds=freshness_threshold_seconds, now=as_of
    )
