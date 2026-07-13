"""CE.2.1 — Model base class (Common Model Contract §5, §10).

Independence (§5) is structural by omission: this base class gives a
concrete Model no reference to any other Model, no reference to CE.3-CE.5,
and no I/O primitives — `estimate()` receives only a ModelInputBundle and
must be a pure function of it (§10 Determinism). There is nothing here a
subclass could use to violate either rule even if it tried, short of
importing something it has no business importing (guarded per-Model by
test_contract.py in each Model's own test suite, CE.2.2+).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from tbos.ce2_prediction.contract import ModelOutput
from tbos.ce2_prediction.input_bundle import ModelInputBundle


class Model(ABC):
    domain: ClassVar[str]
    model_id: ClassVar[str]
    version: ClassVar[str]
    required_fields: ClassVar[list[str]]
    optional_fields: ClassVar[list[str]] = []

    @abstractmethod
    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        """Must be a pure function of `bundle` alone: no network calls, no
        clock reads beyond what's already inside `bundle`, no shared
        mutable state between calls. See assert_deterministic in
        determinism.py, which every concrete Model's test suite must run.
        """
        raise NotImplementedError
