"""Global taxonomy enums shared across all TBOS Engines and Models.

These are the single source of truth for epistemic tags, categorical
classifications, and lifecycle states used throughout the system. No
Engine or Model may define a competing enum for the same concept.
"""

from enum import StrEnum


class InformationReliability(StrEnum):
    """Epistemic status of a data point, per the DIKW information hierarchy."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    OPINION = "OPINION"


class EdgeSourceCategory(StrEnum):
    """Why an edge is believed to exist (CE.3 tags, IL.3 aggregates by this)."""

    INFORMATIONAL = "INFORMATIONAL"
    MODEL = "MODEL"
    BEHAVIORAL_MARKET_BIAS = "BEHAVIORAL_MARKET_BIAS"
    STRUCTURAL = "STRUCTURAL"


class MechanismStability(StrEnum):
    """IL.3: whether an edge's underlying mechanism is stable or drifting."""

    MECHANISM_STABLE = "MECHANISM_STABLE"
    MECHANISM_SHIFTING = "MECHANISM_SHIFTING"
    MECHANISM_UNKNOWN = "MECHANISM_UNKNOWN"


class EdgeLifecycle(StrEnum):
    """CE.3: per-bet classification of an edge's temporal stage."""

    EMERGING = "EMERGING"
    STABLE = "STABLE"
    DECAYING = "DECAYING"
    UNKNOWN = "UNKNOWN"


class ActionType(StrEnum):
    """CE.4: the full action space a decision may resolve to."""

    BET_NOW = "BET_NOW"
    WAIT_FOR_PRICE = "WAIT_FOR_PRICE"
    MONITOR_LIVE_CONDITION = "MONITOR_LIVE_CONDITION"
    SPLIT_EXPOSURE = "SPLIT_EXPOSURE"
    DEFER = "DEFER"
    PASS = "PASS"


class InstrumentType(StrEnum):
    MONEYLINE = "MONEYLINE"
    HANDICAP = "HANDICAP"
    TOTALS = "TOTALS"
    SET_BETTING = "SET_BETTING"
    LIVE = "LIVE"


class ModelLifecycleStatus(StrEnum):
    """Model Registry lifecycle — a Model may only be invoked live when ACTIVE."""

    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"


class ValidationStatus(StrEnum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class BetStatus(StrEnum):
    """INF.2: status derived from the last non-corrected event in a bet's chain."""

    DECIDED = "DECIDED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    AWAITING_SETTLEMENT = "AWAITING_SETTLEMENT"
    SETTLED = "SETTLED"


class ConfidenceFlag(StrEnum):
    """CE.2 Abstention Policy: the only three valid publication states."""

    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    ABSTAINED = "ABSTAINED"


class OutcomeResult(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    VOID = "VOID"
    PUSH = "PUSH"


class DecisionQualityClassification(StrEnum):
    """INF.3 §D — evaluated against info available AT DECISION TIME, never
    with outcome hindsight folded back into what counted as a good call.
    """

    GOOD_DECISION_GOOD_OUTCOME = "GOOD_DECISION_GOOD_OUTCOME"
    GOOD_DECISION_BAD_OUTCOME = "GOOD_DECISION_BAD_OUTCOME"
    BAD_DECISION_GOOD_OUTCOME = "BAD_DECISION_GOOD_OUTCOME"
    BAD_DECISION_BAD_OUTCOME = "BAD_DECISION_BAD_OUTCOME"
    AMBIGUOUS = "AMBIGUOUS"


class DecisionConfidenceTier(StrEnum):
    """How strong the reasoning was, as assessed by CE.4 at decision time —
    independent of and prior to knowing the outcome.
    """

    STRONG = "STRONG"
    MARGINAL = "MARGINAL"
    WEAK = "WEAK"


class MistakeCategory(StrEnum):
    MODEL_ERROR = "MODEL_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    BEHAVIORAL_ERROR = "BEHAVIORAL_ERROR"
    MARKET_MISREAD = "MARKET_MISREAD"
    UNKNOWN_UNKNOWN = "UNKNOWN_UNKNOWN"


class FindingStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    UNDER_REVIEW = "UNDER_REVIEW"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"


class CancellationReason(StrEnum):
    PRECONDITION_TIMEOUT = "PRECONDITION_TIMEOUT"
    LIQUIDITY_INSUFFICIENT = "LIQUIDITY_INSUFFICIENT"
    PRICE_MOVED_OUT_OF_BAND = "PRICE_MOVED_OUT_OF_BAND"
    BOOKMAKER_UNAVAILABLE = "BOOKMAKER_UNAVAILABLE"


class PaperTradingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class ApprovalDecision(StrEnum):
    APPROVE_LIVE = "APPROVE_LIVE"
    REJECT = "REJECT"
    EXTEND_RUN = "EXTEND_RUN"


class MonitorStatus(StrEnum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    EXPIRED = "EXPIRED"


class PersistenceClass(StrEnum):
    SECONDS = "SECONDS"
    MINUTES = "MINUTES"
    HOURS = "HOURS"


class ExecutionMode(StrEnum):
    """Tags every ModelOutput with how it was produced. The Ensemble
    Aggregator's ingestion contract accepts LIVE only — SHADOW/BACKTEST
    outputs are structurally ineligible for real combination, not merely
    excluded by convention (CE.2.8 Shadow Execution spec).
    """

    LIVE = "LIVE"
    SHADOW = "SHADOW"
    BACKTEST = "BACKTEST"


class EventType(StrEnum):
    """INF.2 event stream — the only six event types the Bet Ledger accepts."""

    DECISION_RECORDED = "DECISION_RECORDED"
    EXECUTION_RECORDED = "EXECUTION_RECORDED"
    CANCELLATION_RECORDED = "CANCELLATION_RECORDED"
    CLV_RECORDED = "CLV_RECORDED"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    CORRECTION_RECORDED = "CORRECTION_RECORDED"


class Surface(StrEnum):
    CLAY = "CLAY"
    HARD = "HARD"
    GRASS = "GRASS"
    INDOOR_HARD = "INDOOR_HARD"
    CARPET = "CARPET"


class BestOf(StrEnum):
    BO3 = "BO3"
    BO5 = "BO5"


class FieldAvailability(StrEnum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    PARTIAL = "PARTIAL"


class FieldValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
