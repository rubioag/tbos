"""CE.3 — Edge Persistence, degraded mode (spec §Persistence): IL.3 Edge
Attribution doesn't exist yet, so per-category historical decay data isn't
available. Falls back to a documented category-default heuristic — this
is exactly the graceful-degradation path the frozen spec anticipated, not
a placeholder to silently forget about.
"""

from __future__ import annotations

from pydantic import BaseModel

from tbos.inf1_config.taxonomy import EdgeSourceCategory, PersistenceClass

_CATEGORY_DEFAULTS: dict[EdgeSourceCategory, tuple[PersistenceClass, float]] = {
    EdgeSourceCategory.INFORMATIONAL: (PersistenceClass.SECONDS, 30.0),
    EdgeSourceCategory.BEHAVIORAL_MARKET_BIAS: (PersistenceClass.MINUTES, 600.0),
    EdgeSourceCategory.MODEL: (PersistenceClass.HOURS, 6 * 3600.0),
    EdgeSourceCategory.STRUCTURAL: (PersistenceClass.HOURS, 24 * 3600.0),
}


class EdgePersistence(BaseModel):
    estimate_seconds: float
    persistence_class: PersistenceClass
    based_on: str


def estimate_persistence(category: EdgeSourceCategory) -> EdgePersistence:
    persistence_class, seconds = _CATEGORY_DEFAULTS[category]
    return EdgePersistence(estimate_seconds=seconds, persistence_class=persistence_class, based_on="category_default_heuristic")
