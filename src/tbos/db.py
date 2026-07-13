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
