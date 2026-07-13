"""CE.6 — CLVRecord. Measurement Independence Principle, structurally
enforced: no field here can ever reference match outcome, win/loss, or
ROI. CE.6 measures market prediction quality only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from tbos.inf1_config.taxonomy import EdgeSourceCategory, InstrumentType


class CLVRecord(BaseModel):
    clv_id: uuid.UUID
    action_plan_id: uuid.UUID
    match_id: str
    instrument_type: InstrumentType
    book_id: str

    placed_odds: float
    closing_odds: float
    placed_implied_probability: float
    closing_implied_probability: float
    clv_value: float
    vig_adjusted: bool
    vig_adjustment_method: str

    edge_source_category: EdgeSourceCategory

    ce6_engine_version: str
    computed_at: datetime
