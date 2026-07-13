from tbos.ce3_edge.lifecycle import classify_lifecycle
from tbos.inf1_config.taxonomy import EdgeLifecycle, EdgeSourceCategory


def test_informational_defaults_to_emerging() -> None:
    assert classify_lifecycle(EdgeSourceCategory.INFORMATIONAL) == EdgeLifecycle.EMERGING


def test_structural_defaults_to_stable() -> None:
    assert classify_lifecycle(EdgeSourceCategory.STRUCTURAL) == EdgeLifecycle.STABLE


def test_behavioral_bias_defaults_to_stable() -> None:
    assert classify_lifecycle(EdgeSourceCategory.BEHAVIORAL_MARKET_BIAS) == EdgeLifecycle.STABLE


def test_model_sourced_defaults_to_unknown() -> None:
    assert classify_lifecycle(EdgeSourceCategory.MODEL) == EdgeLifecycle.UNKNOWN
