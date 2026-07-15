from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from tbos.settings import settings


class Base(DeclarativeBase):
    """Shared declarative base for every TBOS module's ORM models."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Created lazily so importing tbos.db (e.g. for Base.metadata in tests
    that use SQLite) never requires the production DB driver to be installed.
    """
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def ensure_schema(engine: Engine | None = None) -> None:
    """Idempotent: `Base.metadata.create_all` only creates tables that
    don't exist yet, safe to call on every startup.

    `Base.metadata` only knows about a model class once its module has
    been imported (SQLAlchemy declarative registration is an import-time
    side effect) — tests get this for free because pytest collection
    imports everything, but a standalone process (the CLI) does not.
    There is no Alembic migration wiring yet (the `alembic/` directory is
    an empty scaffold) — this is the minimal real fix so `tbos paper-run`
    can create its own schema on a fresh database instead of crashing
    with "no such table".
    """
    import importlib

    model_modules = (
        "ce1_data", "ce2_prediction", "ce3_edge", "ce4_decision", "ce5_execution",
        "ce6_clv", "inf1_config", "inf2_ledger", "inf3_review", "paper_trading",
    )
    for package_name in model_modules:
        importlib.import_module(f"tbos.{package_name}.models")

    Base.metadata.create_all(engine or get_engine())
