from tbos.ce3_edge.persistence import estimate_persistence
from tbos.inf1_config.taxonomy import EdgeSourceCategory, PersistenceClass


def test_informational_edge_persists_seconds() -> None:
    result = estimate_persistence(EdgeSourceCategory.INFORMATIONAL)
    assert result.persistence_class == PersistenceClass.SECONDS


def test_structural_edge_persists_hours() -> None:
    result = estimate_persistence(EdgeSourceCategory.STRUCTURAL)
    assert result.persistence_class == PersistenceClass.HOURS


def test_behavioral_bias_edge_persists_minutes() -> None:
    result = estimate_persistence(EdgeSourceCategory.BEHAVIORAL_MARKET_BIAS)
    assert result.persistence_class == PersistenceClass.MINUTES


def test_informational_persists_shorter_than_structural() -> None:
    informational = estimate_persistence(EdgeSourceCategory.INFORMATIONAL)
    structural = estimate_persistence(EdgeSourceCategory.STRUCTURAL)
    assert informational.estimate_seconds < structural.estimate_seconds


def test_result_is_honestly_labeled_as_heuristic() -> None:
    result = estimate_persistence(EdgeSourceCategory.MODEL)
    assert result.based_on == "category_default_heuristic"
