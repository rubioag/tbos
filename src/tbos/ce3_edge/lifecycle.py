"""CE.3 — Edge Lifecycle classification, degraded mode: same deferral
rationale as persistence.py — IL.3 doesn't exist yet to supply real
historical decay patterns, so this falls back to a category-default
heuristic rather than a fabricated trend. MODEL-sourced edges default to
UNKNOWN since a Model-driven edge has no inherent temporal signature; the
other three categories have a directionally reasonable default.
"""

from __future__ import annotations

from tbos.inf1_config.taxonomy import EdgeLifecycle, EdgeSourceCategory

_CATEGORY_DEFAULTS: dict[EdgeSourceCategory, EdgeLifecycle] = {
    EdgeSourceCategory.INFORMATIONAL: EdgeLifecycle.EMERGING,
    EdgeSourceCategory.BEHAVIORAL_MARKET_BIAS: EdgeLifecycle.STABLE,
    EdgeSourceCategory.STRUCTURAL: EdgeLifecycle.STABLE,
    EdgeSourceCategory.MODEL: EdgeLifecycle.UNKNOWN,
}


def classify_lifecycle(category: EdgeSourceCategory) -> EdgeLifecycle:
    return _CATEGORY_DEFAULTS.get(category, EdgeLifecycle.UNKNOWN)
