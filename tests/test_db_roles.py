"""Runtime role: created by the migration owner, limited to row access."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db.models import Base
from app.db.seed import seed_catalog
from scripts import db_roles

pytestmark = pytest.mark.postgres
FIRST, SECOND = "first-synthetic-role-pass%", "second-synthetic-role-pass"


@pytest.fixture
def runtime_role(engine, monkeypatch):
    owner_url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", owner_url)
    monkeypatch.delenv("DATABASE_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_ALLOWED_HOSTS", raising=False)
    settings, role_settings = db_roles.Settings, db_roles.RoleSettings
    monkeypatch.setattr(db_roles, "Settings", lambda: settings(_env_file=None))
    monkeypatch.setattr(db_roles, "RoleSettings", lambda: role_settings(_env_file=None))
    yield lambda password: engine.url.set(username=db_roles.APP_ROLE, password=password)
    with engine.begin() as connection:
        if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'clinic_app'")).first():
            connection.execute(text("DROP OWNED BY clinic_app"))
            connection.execute(text("DROP ROLE clinic_app"))


def connect(url):
    instance = create_engine(url, connect_args={"connect_timeout": 5})
    return instance, instance.connect()


def test_runtime_role_has_row_access_only(runtime_role, monkeypatch):
    monkeypatch.setenv("CLINIC_APP_PASSWORD", FIRST)
    db_roles.main()
    monkeypatch.setenv("CLINIC_APP_PASSWORD", SECOND)
    db_roles.main()  # idempotent; the second run resets the password
    instance, connection = connect(runtime_role(SECOND))
    try:
        for table in Base.metadata.tables:
            for privilege in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
                assert connection.execute(
                    text("SELECT has_table_privilege(:t, :p)"), {"t": table, "p": privilege}
                ).scalar(), (table, privilege)
        with Session(bind=connection) as session:
            seed_catalog(session)
            session.rollback()
        for statement in [
            "CREATE TABLE intruder (id int)",
            "DROP TABLE appointments",
            "ALTER TABLE appointments ADD COLUMN extra int",
            "TRUNCATE conversation_items",
            "UPDATE alembic_version SET version_num = version_num",
        ]:
            with pytest.raises(ProgrammingError):
                with connection.begin():
                    connection.execute(text(statement))
    finally:
        connection.close()
        instance.dispose()
    with pytest.raises(Exception):
        connect(runtime_role(FIRST))


def test_runtime_role_needs_a_guarded_target_and_a_long_password(runtime_role, monkeypatch):
    monkeypatch.setenv("CLINIC_APP_PASSWORD", "short")
    with pytest.raises(ValueError):
        db_roles.main()
    monkeypatch.setenv("CLINIC_APP_PASSWORD", FIRST)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://clinic_demo:x@remote.example/clinic_scheduling_dev"
    )
    with pytest.raises(ValueError):
        db_roles.main()
