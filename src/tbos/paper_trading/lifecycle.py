"""Paper Trading run lifecycle: ACTIVE -> PASSED | FAILED | ABORTED.
Terminal states never transition further — same discipline as Model
Registry and Finding review gates.
"""

from __future__ import annotations

from tbos.inf1_config.taxonomy import PaperTradingStatus

ALLOWED_TRANSITIONS: dict[PaperTradingStatus, set[PaperTradingStatus]] = {
    PaperTradingStatus.ACTIVE: {PaperTradingStatus.PASSED, PaperTradingStatus.FAILED, PaperTradingStatus.ABORTED},
    PaperTradingStatus.PASSED: set(),
    PaperTradingStatus.FAILED: set(),
    PaperTradingStatus.ABORTED: set(),
}


class InvalidRunTransition(RuntimeError):
    pass


def validate_transition(current: PaperTradingStatus, target: PaperTradingStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidRunTransition(f"{current} -> {target} is not a valid Paper Trading run transition")
