"""CE.3 — Edge Description Engine pipeline (spec §B).

    CE.2 PredictionOutput -> fair odds -> EV distribution -> robustness
    -> persistence -> sensitivity -> lifecycle -> EdgeDescription

Decision-neutral throughout: never selects, ranks, or recommends — only
describes. `edge_source_category` isn't auto-tagged yet (would need CE.2's
Explainability Report, not built) — caller supplies it explicitly,
defaulting to MODEL since predictions are currently Model-ensemble-driven
rather than informational-signal-driven (IL.1 doesn't exist yet either).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from tbos.ce2_prediction.prediction_engine import PredictionOutput
from tbos.ce3_edge.ev import compute_ev_distribution
from tbos.ce3_edge.fair_odds import fair_odds_from_probability
from tbos.ce3_edge.lifecycle import classify_lifecycle
from tbos.ce3_edge.persistence import estimate_persistence
from tbos.ce3_edge.robustness import compute_robustness
from tbos.ce3_edge.schemas import EdgeDescription
from tbos.ce3_edge.sensitivity import run_sensitivity_analysis
from tbos.inf1_config.taxonomy import EdgeSourceCategory, InstrumentType

CE3_ENGINE_VERSION = "1.0.0"


def build_edge_description(
    prediction: PredictionOutput,
    *,
    instrument_type: InstrumentType,
    book_id: str,
    offered_odds: float,
    as_of: datetime,
    edge_source_category: EdgeSourceCategory = EdgeSourceCategory.MODEL,
) -> EdgeDescription | None:
    """Returns None when CE.2 produced no usable probability (ABSTAINED) —
    there is nothing CE.3 can honestly describe without one. Never
    fabricates a description from missing upstream data (spec §9).
    """
    if prediction.probability_player_a is None or prediction.uncertainty is None:
        return None

    fair_odds = fair_odds_from_probability(prediction.probability_player_a)
    ev_distribution = compute_ev_distribution(prediction.probability_player_a, prediction.uncertainty, offered_odds)
    robustness = compute_robustness(ev_distribution)
    persistence = estimate_persistence(edge_source_category)
    sensitivity = run_sensitivity_analysis(prediction.probability_player_a, offered_odds)
    lifecycle = classify_lifecycle(edge_source_category)

    return EdgeDescription(
        edge_id=uuid.uuid4(),
        match_id=prediction.match_id,
        instrument_type=instrument_type,
        book_id=book_id,
        probability_used=prediction.probability_player_a,
        probability_uncertainty=prediction.uncertainty,
        fair_odds=fair_odds,
        offered_odds=offered_odds,
        ev_distribution=ev_distribution,
        edge_robustness=robustness,
        edge_persistence=persistence,
        sensitivity_analysis=sensitivity,
        edge_lifecycle=lifecycle,
        edge_source_category=edge_source_category,
        ce3_engine_version=CE3_ENGINE_VERSION,
        computed_at=as_of,
    )
