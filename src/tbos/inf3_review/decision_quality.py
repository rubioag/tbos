"""INF.3 §D — Decision Quality Classification.

`confidence_tier` must be supplied by the caller from the decision's
actual EV/Robustness assessment at decision time (CE.3/CE.4, not yet
built) — this module never infers confidence from the outcome, which
would be exactly the hindsight bias the classification exists to prevent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from tbos.inf1_config.taxonomy import DecisionConfidenceTier, DecisionQualityClassification, OutcomeResult

_MATRIX: dict[tuple[DecisionConfidenceTier, OutcomeResult], DecisionQualityClassification] = {
    (DecisionConfidenceTier.STRONG, OutcomeResult.WIN): DecisionQualityClassification.GOOD_DECISION_GOOD_OUTCOME,
    (DecisionConfidenceTier.STRONG, OutcomeResult.LOSS): DecisionQualityClassification.GOOD_DECISION_BAD_OUTCOME,
    (DecisionConfidenceTier.WEAK, OutcomeResult.WIN): DecisionQualityClassification.BAD_DECISION_GOOD_OUTCOME,
    (DecisionConfidenceTier.WEAK, OutcomeResult.LOSS): DecisionQualityClassification.BAD_DECISION_BAD_OUTCOME,
}


class DecisionQualityRecord(BaseModel):
    bet_id: uuid.UUID
    classification: DecisionQualityClassification
    confidence_tier: DecisionConfidenceTier
    outcome: OutcomeResult
    classification_rules_version: str
    evaluated_at: datetime


def classify_decision(
    *,
    bet_id: uuid.UUID,
    confidence_tier: DecisionConfidenceTier,
    outcome: OutcomeResult,
    classification_rules_version: str = "1.0.0",
    evaluated_at: datetime,
) -> DecisionQualityRecord:
    """MARGINAL confidence and VOID/PUSH outcomes are always AMBIGUOUS —
    there is no clean signal to classify against in either case.
    """
    if outcome in (OutcomeResult.VOID, OutcomeResult.PUSH) or confidence_tier == DecisionConfidenceTier.MARGINAL:
        classification = DecisionQualityClassification.AMBIGUOUS
    else:
        classification = _MATRIX[(confidence_tier, outcome)]

    return DecisionQualityRecord(
        bet_id=bet_id,
        classification=classification,
        confidence_tier=confidence_tier,
        outcome=outcome,
        classification_rules_version=classification_rules_version,
        evaluated_at=evaluated_at,
    )
