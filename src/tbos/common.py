"""Cross-cutting infrastructure shared by every append-only table across
TBOS modules (INF.1 ConfigVersion, CE.1 Snapshot, INF.2 events, ...).
"""


class ImmutableRecordError(RuntimeError):
    """Raised when code attempts to UPDATE or DELETE an append-only row."""


def forbid_mutation(mapper: object, connection: object, target: object) -> None:
    raise ImmutableRecordError(
        f"{type(target).__name__} is append-only; UPDATE/DELETE is not permitted. "
        "Publish a new version instead."
    )
