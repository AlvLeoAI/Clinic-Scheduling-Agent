"""Fail closed before mutations; no reset, truncate, downgrade or development DB access."""

import hashlib
import json

from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from alembic import command
from app.db.models import Base
from app.db.safety import require_demo_database
from app.db.seed import seed_catalog
from evaluations.runner import ROOT


def validate_url(raw):
    url = require_demo_database(raw, test_only=True)
    if url.host != "127.0.0.1" or url.port != 15433:
        raise ValueError("R2 requires the dedicated 127.0.0.1:15433 synthetic test endpoint.")
    return url


def verify_identity(engine, expected_system_id):
    validate_url(engine.url.render_as_string(hide_password=False))
    if not expected_system_id or not expected_system_id.isdigit():
        raise ValueError("A separately verified synthetic cluster system identifier is required.")
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT current_database(), current_user, system_identifier::text "
                "FROM pg_control_system()"
            )
        ).one()
        databases = set(conn.scalars(text("SELECT datname FROM pg_database")))
    if tuple(row) != ("clinic_scheduling_test", "clinic_demo", expected_system_id) or databases - {
        "postgres",
        "template0",
        "template1",
        "clinic_scheduling_test",
    }:
        raise ValueError("Database identity/isolation did not match the dedicated test cluster.")
    return {
        "host": "127.0.0.1",
        "port": 15433,
        "database": row[0],
        "role": row[1],
        "system_identifier": row[2],
        "other_application_databases": [],
    }


def database_snapshot(engine):
    """Private integrity digest, including all columns; never serialize token hashes in reports."""
    with engine.connect() as conn:
        state = {
            name: sorted(
                [dict(r) for r in conn.execute(select(table)).mappings()],
                key=lambda row: str(row.get("id", "")),
            )
            for name, table in Base.metadata.tables.items()
        }
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()


def require_fixture(engine):
    """Require exact seed truth and empty runtime tables, without overwriting unknown rows."""
    if set(inspect(engine).get_table_names()) != set(Base.metadata.tables) | {"alembic_version"}:
        raise ValueError("The approved migrated schema is required.")
    catalog = {"clinics", "practitioners", "appointment_types", "weekly_schedules"}
    with engine.connect() as conn:
        if conn.scalar(text("SELECT version_num FROM alembic_version")) != "0001":
            raise ValueError("The approved migration revision is required.")
        before = {
            name: [dict(r) for r in conn.execute(select(Base.metadata.tables[name])).mappings()]
            for name in catalog
        }
    from datetime import time
    from uuid import uuid5

    from app.db.seed import CLINIC_ID, PRACTITIONER_IDS, TYPE_IDS

    expected = {
        "clinics": [
            {"id": CLINIC_ID, "name": "Synthetic Demo Clinic", "timezone": "America/Chicago"}
        ],
        "practitioners": [
            {
                "id": p,
                "clinic_id": CLINIC_ID,
                "display_name": f"Demo Clinician {i:02}",
                "is_active": True,
            }
            for i, p in enumerate(PRACTITIONER_IDS, 1)
        ],
        "appointment_types": [
            {
                "id": p,
                "clinic_id": CLINIC_ID,
                "code": code,
                "duration_minutes": duration,
                "is_active": True,
            }
            for p, code, duration in zip(TYPE_IDS, ("follow_up", "initial_consultation"), (30, 60))
        ],
        "weekly_schedules": [
            {
                "id": uuid5(p, f"weekday:{day}"),
                "practitioner_id": p,
                "weekday": day,
                "opens_at": time(9),
                "closes_at": time(17),
            }
            for p in PRACTITIONER_IDS
            for day in range(1, 6)
        ],
    }

    def normalize(rows):
        return sorted(
            [{k: v for k, v in r.items() if k != "created_at"} for r in rows],
            key=lambda r: str(r["id"]),
        )

    if any(normalize(before[name]) != normalize(expected[name]) for name in catalog):
        raise ValueError("Catalog is not the exact approved synthetic fixture; no overwrite.")
    with engine.connect() as conn:
        for name, table in Base.metadata.tables.items():
            if name not in catalog and conn.execute(select(table).limit(1)).first():
                raise ValueError("Runtime tables must be empty; existing rows are preserved.")


def prepare_database(engine, expected_system_id):
    identity = verify_identity(engine, expected_system_id)
    tables = set(inspect(engine).get_table_names())
    expected = set(Base.metadata.tables) | {"alembic_version"}
    if tables and tables != expected:
        raise ValueError("Unknown or partially migrated schema; no automatic repair/reset.")
    if not tables:
        config = Config(str(ROOT / "alembic.ini"))
        with engine.connect() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
    with engine.connect() as conn:
        any_rows = any(
            conn.execute(select(t).limit(1)).first() for t in Base.metadata.tables.values()
        )
    if not any_rows:
        verify_identity(engine, expected_system_id)
        with Session(engine) as db:
            seed_catalog(db)
            db.commit()
    require_fixture(engine)
    return identity
