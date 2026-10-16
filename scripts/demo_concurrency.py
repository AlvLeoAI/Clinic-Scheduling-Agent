"""Controlled real-PostgreSQL overlap race; no global reset or OpenAI calls."""

# ruff: noqa: E402 -- direct-file invocation needs the repository root on sys.path.

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch
from uuid import UUID, uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Appointment, BookingProposal, IdempotencyRecord
from app.db.seed import PRACTITIONER_IDS, TYPE_IDS
from app.db.session import build_engine
from app.main import create_app
from app.schemas.scheduling import AvailabilityResponse
from app.services.booking import BookingService
from evaluations.oracle import slots
from scripts.demo_support import NOW, cleanup_owned, demo_settings, prepare, validate_engine


def run_demo(settings, engine):
    from app.db.safety import require_demo_database

    require_demo_database(settings.database_url.get_secret_value(), test_only=True)
    validate_engine(settings, engine)
    owners, clients, engines = [], [], []
    barrier, inserted = Barrier(2), Event()
    pids, violations = [], []
    try:
        with Session(engine) as db:
            if db.scalar(select(func.count()).select_from(Appointment)):
                raise ValueError(
                    "Demo requires an empty appointment table in the designated test DB; "
                    "nothing was reset."
                )
        for _ in range(2):
            independent = build_engine(settings)
            engines.append(independent)
            app = create_app(settings, independent, clock=lambda: NOW)
            client = TestClient(app)
            client.__enter__()
            clients.append(client)
            body = client.post("/api/v1/sessions", json={}).json()
            owners.append(
                {
                    "id": UUID(body["session_id"]),
                    "headers": {"Authorization": "Bearer " + body["session_token"]},
                }
            )
        proposals, keys = [], [str(uuid4()), str(uuid4())]
        for index, owner in enumerate(owners):
            response = clients[index].post(
                "/api/v1/proposals",
                headers=owner["headers"],
                json={
                    "practitioner_id": str(PRACTITIONER_IDS[0]),
                    "appointment_type_id": str(TYPE_IDS[1 if index == 0 else 0]),
                    "local_date": "2030-01-09",
                    "local_time": "09:00" if index == 0 else "09:30",
                },
            )
            assert response.status_code == 201
            proposals.append(response.json())
        original = BookingService._insert_appointment

        def coordinated(service, row, now):
            pids.append(service.db.scalar(text("SELECT pg_backend_pid()")))
            barrier.wait(timeout=5)  # Both real requests passed policy/availability preflight.
            if row.duration_minutes == 60:
                result = original(service, row, now)
                inserted.set()
                return result
            assert inserted.wait(timeout=5)
            try:
                return original(service, row, now)
            except IntegrityError as exc:
                violations.append(
                    {"sqlstate": exc.orig.sqlstate, "constraint": exc.orig.diag.constraint_name}
                )
                raise

        def confirm(index):
            return clients[index].post(
                f"/api/v1/proposals/{proposals[index]['proposal_id']}/confirm",
                headers={**owners[index]["headers"], "Idempotency-Key": keys[index]},
                json={},
            )

        with (
            patch.object(BookingService, "_insert_appointment", coordinated),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [pool.submit(confirm, index) for index in range(2)]
            responses = [future.result(timeout=12) for future in futures]
        assert [r.status_code for r in responses] == [201, 409]
        assert responses[1].json()["error"]["code"] == "SLOT_TAKEN"
        assert len(set(pids)) == 2 and violations == [
            {"sqlstate": "23P01", "constraint": "appointments_no_overlap"}
        ]
        # A third engine/pool establishes independent post-commit database truth.
        verification = build_engine(settings)
        try:
            with Session(verification) as db:
                rows = db.scalars(select(Appointment)).all()
                assert len(rows) == 1 and rows[0].session_id == owners[0]["id"]
                appointment = {
                    "id": str(rows[0].id),
                    "practitioner_id": str(rows[0].practitioner_id),
                    "starts_at": rows[0].starts_at.isoformat(),
                    "ends_at": rows[0].ends_at.isoformat(),
                }
                states = {
                    str(row.id): row.status
                    for row in db.scalars(
                        select(BookingProposal).where(
                            BookingProposal.session_id.in_([o["id"] for o in owners])
                        )
                    )
                }
                assert [states[p["proposal_id"]] for p in proposals] == ["CONFIRMED", "CONFLICTED"]
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(IdempotencyRecord)
                        .where(IdempotencyRecord.session_id.in_([o["id"] for o in owners]))
                    )
                    == 2
                )
                verification_pid = db.scalar(text("SELECT pg_backend_pid()"))
        finally:
            verification.dispose()
        for index in range(2):
            replay = confirm(index)
            assert (
                replay.status_code == responses[index].status_code
                and replay.content == responses[index].content
            )
        query = {
            "date": "2030-01-09",
            "practitioner_id": str(PRACTITIONER_IDS[0]),
            "appointment_type_id": str(TYPE_IDS[0]),
        }
        response = clients[1].get(
            "/api/v1/availability", params=query, headers=owners[1]["headers"]
        )
        assert response.status_code == 200
        availability = AvailabilityResponse.model_validate(response.json()).model_dump(mode="json")
        expected = slots(
            {
                "local_date": query["date"],
                "practitioner_id": query["practitioner_id"],
                "appointment_type_id": query["appointment_type_id"],
            },
            {
                "practitioners": [str(v) for v in PRACTITIONER_IDS],
                "types": {str(TYPE_IDS[0]): 30, str(TYPE_IDS[1]): 60},
            },
            NOW,
            [appointment],
        )
        assert availability["slots"] == expected and len(expected) == 14
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Appointment)) == 1
        evidence = {
            "status": "PASS",
            "database": "clinic_scheduling_test",
            "clock": NOW.isoformat(),
            "independent_clients": 2,
            "confirmation_backend_pids": pids,
            "verification_backend_pid": verification_pid,
            "responses": [201, 409],
            "conflict": violations[0],
            "appointment_count_verified": 1,
            "appointment": appointment,
            "proposal_states": states,
            "same_key_replays_byte_identical": True,
            "alternative_slots_verified": availability["slots"],
            "trace_ids": [r.json()["trace_id"] for r in responses],
            "live_provider_calls": 0,
            "global_reset": False,
            "transient_demo_rows": True,
        }
    finally:
        for client in clients:
            client.__exit__(None, None, None)
        for independent in engines:
            independent.dispose()
        cleanup_owned(engine, [o["id"] for o in owners])
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Appointment)) == 0
    evidence["owned_rows_cleaned"] = True
    return evidence


def main():
    parser = argparse.ArgumentParser(
        description="Synthetic-only concurrent booking proof; never a global reset."
    )
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if not args.synthetic_only:
        parser.error("--synthetic-only is required before connecting or mutating.")
    logging.getLogger("clinic.requests").setLevel(logging.WARNING)
    engine = None
    try:
        settings = demo_settings()
        engine = prepare(settings)
        result = run_demo(settings, engine)
        if args.evidence:
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "message": "Synthetic demo failed safely; no outcome is inferred "
                    "and no global reset performed.",
                }
            )
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
