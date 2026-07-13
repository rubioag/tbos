import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tbos.db import Base


@pytest.fixture()
def session() -> Session:
    """In-memory SQLite for fast unit tests. JSON is used instead of JSONB
    (models.py declares a JSON/JSONB variant), UUID via SQLAlchemy's
    dialect-agnostic Uuid type — same logical schema as PostgreSQL.
    """
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s
