"""Contract test: every EventType the taxonomy defines must have exactly
one payload schema, and vice versa — a drift here means replay_bet's
match statement silently falls through to its ValueError branch, or a
payload schema exists for a type nothing can ever write.
"""

from tbos.inf1_config.taxonomy import EventType
from tbos.inf2_ledger.events import EVENT_PAYLOAD_SCHEMAS


def test_every_event_type_has_exactly_one_payload_schema() -> None:
    assert set(EVENT_PAYLOAD_SCHEMAS.keys()) == {t.value for t in EventType}
