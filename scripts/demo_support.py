"""Only dedicated synthetic test DBs; scoped fixture cleanup, never a global reset."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings
from app.db.models import (
    Appointment,
    BookingProposal,
    ChatSession,
    ChatTurn,
    ConversationItem,
    IdempotencyRecord,
)
from app.db.safety import require_demo_database
from app.db.seed import seed_catalog
from app.db.session import build_engine

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2030, 1, 7, 15, tzinfo=UTC)


def demo_settings():
    source = Settings()
    if source.test_database_url is None:
        raise ValueError("TEST_DATABASE_URL is required for this synthetic demo.")
    url = source.test_database_url.get_secret_value()
    require_demo_database(url, test_only=True)  # Before connect, migrate, seed or cleanup.
    return Settings(
        _env_file=None,
        database_url=url,
        enable_live_openai=False,
        openai_api_key=None,
        openai_model="synthetic-offline-demo",
    )


def prepare(settings):
    require_demo_database(settings.database_url.get_secret_value(), test_only=True)
    engine = build_engine(settings)
    try:
        config = Config(str(ROOT / "alembic.ini"))
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with Session(engine) as db, db.begin():
            seed_catalog(db)
        return engine
    except Exception:
        engine.dispose()
        raise


def cleanup_owned(engine, owners):
    require_demo_database(engine.url.render_as_string(hide_password=False), test_only=True)
    ids = [UUID(str(owner)) for owner in owners]
    if not ids:
        return
    with Session(engine) as db, db.begin():
        for row in db.scalars(select(ChatSession).where(ChatSession.id.in_(ids))):
            row.active_turn_id = None
        db.flush()
        for model in (
            IdempotencyRecord,
            Appointment,
            BookingProposal,
            ConversationItem,
            ChatTurn,
            ChatSession,
        ):
            field = model.id if model is ChatSession else model.session_id
            db.execute(delete(model).where(field.in_(ids)))


def validate_engine(settings, engine):
    expected = require_demo_database(settings.database_url.get_secret_value(), test_only=True)
    actual = require_demo_database(engine.url.render_as_string(hide_password=False), test_only=True)
    if make_url(expected) != make_url(actual):
        raise ValueError("Demo engine must match the validated test configuration.")
