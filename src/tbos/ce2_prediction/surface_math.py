"""Shared pure math utilities for by-surface stat lookups. Neutral module —
owned by neither Serve nor Return Model, so importing this never counts as
one Model reading another (Common Model Contract §5 independence).
"""

from __future__ import annotations


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def surface_value(by_surface: dict[str, float], surface_key: str) -> float | None:
    return by_surface.get(surface_key)
