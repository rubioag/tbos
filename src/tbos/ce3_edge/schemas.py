"""CE.3 — EdgeDescription: the complete, decision-neutral description of
one opportunity for one instrument/book. Never ranked, never selected —
per the frozen spec's Decision Independence rule, enforced structurally
by having no rank/score-for-selection field anywhere in this schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from tbos.ce3_edge.ev import EVDistribution
from tbos.ce3_edge.persistence import EdgePersistence
from tbos.ce3_edge.robustness import RobustnessScore
from tbos.ce3_edge.sensitivity import SensitivityAnalysis
from tbos.inf1_config.taxonomy import EdgeLifecycle, EdgeSourceCategory, InstrumentType


class EdgeDescription(BaseModel):
    edge_id: uuid.UUID
    match_id: str
    instrument_type: InstrumentType
    book_id: str

    probability_used: float
    probability_uncertainty: float
    fair_odds: float
    offered_odds: float

    ev_distribution: EVDistribution
    edge_robustness: RobustnessScore
    edge_persistence: EdgePersistence
    sensitivity_analysis: SensitivityAnalysis
    edge_lifecycle: EdgeLifecycle
    edge_source_category: EdgeSourceCategory

    ce3_engine_version: str
    computed_at: datetime
