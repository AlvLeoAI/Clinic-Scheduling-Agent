"""Real PostgreSQL only; all mutations are fenced to the dedicated local test DB."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings
from app.db.safety import require_demo_database
from app.db.seed import seed_catalog
from app.db.session import build_engine

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2030, 1, 7, 15, tzinfo=UTC)


def pytest_collection_modifyitems(items):
    for item in items:
        if not item.get_closest_marker("postgres"):
            item.add_marker(pytest.mark.unit)
        if item.path.name in {
            "test_agent_protocol.py",
            "test_chat.py",
            "test_conversation_store.py",
        }:
            item.add_marker(pytest.mark.agent_offline)


def migrate(engine, target: str, *, downgrade: bool = False):
    config = Config(str(ROOT / "alembic.ini"))
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, target)


@pytest.fixture(scope="session")
def engine():
    settings = Settings()
    if settings.test_database_url is None:
        pytest.fail("TEST_DATABASE_URL required; PostgreSQL gate BLOCKED, no SQLite fallback.")
    raw_url = settings.test_database_url.get_secret_value()
    require_demo_database(raw_url, test_only=True)
    instance = build_engine(Settings(_env_file=None, database_url=raw_url))
    try:
        migrate(instance, "head")
        yield instance
    finally:
        instance.dispose()


@pytest.fixture
def db(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            seed_catalog(session)
            yield session
        transaction.rollback()
