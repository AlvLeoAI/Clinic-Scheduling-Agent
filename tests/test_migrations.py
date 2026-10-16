import pytest
from sqlalchemy import inspect, text

from app.db.models import Base
from tests.conftest import migrate

pytestmark = pytest.mark.postgres


def test_migration_round_trip(engine):
    # Dedicated test DB only. No dev/other DB is reset.
    engine.dispose()
    migrate(engine, "base", downgrade=True)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    migrate(engine, "head")
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
        assert connection.scalar(
            text("SELECT extname FROM pg_extension WHERE extname='btree_gist'")
        )
    fks = inspect(engine).get_foreign_keys("chat_sessions")
    assert any(fk["name"] == "fk_session_active_turn_owner" for fk in fks)


def test_timestamp_columns_and_exclusion(engine):
    inspector = inspect(engine)
    for table in Base.metadata.tables:
        for column in inspector.get_columns(table):
            if column["name"] in {
                "created_at",
                "expires_at",
                "starts_at",
                "ends_at",
                "confirmed_at",
            }:
                assert column["type"].timezone
    with engine.connect() as connection:
        constraint = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'appointments_no_overlap'"
            )
        )
    assert "EXCLUDE USING gist" in constraint and "'[)'::text" in constraint
