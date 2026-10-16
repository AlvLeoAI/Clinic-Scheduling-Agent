"""Catalog constants created from scratch in M0; no legacy JSON imports."""

from datetime import time
from uuid import UUID, uuid5

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import AppointmentType, Clinic, Practitioner, WeeklySchedule

CLINIC_ID = UUID("00000000-0000-4000-8000-000000000001")
PRACTITIONER_IDS = [
    UUID("00000000-0000-4000-8000-000000000101"),
    UUID("00000000-0000-4000-8000-000000000102"),
]
TYPE_IDS = [
    UUID("00000000-0000-4000-8000-000000000201"),
    UUID("00000000-0000-4000-8000-000000000202"),
]


def seed_catalog(db: Session) -> None:
    rows = [
        (
            Clinic,
            [{"id": CLINIC_ID, "name": "Synthetic Demo Clinic", "timezone": "America/Chicago"}],
        ),
        (
            Practitioner,
            [
                {
                    "id": ident,
                    "clinic_id": CLINIC_ID,
                    "display_name": f"Demo Clinician {idx:02}",
                    "is_active": True,
                }
                for idx, ident in enumerate(PRACTITIONER_IDS, 1)
            ],
        ),
        (
            AppointmentType,
            [
                {
                    "id": TYPE_IDS[0],
                    "clinic_id": CLINIC_ID,
                    "code": "follow_up",
                    "duration_minutes": 30,
                    "is_active": True,
                },
                {
                    "id": TYPE_IDS[1],
                    "clinic_id": CLINIC_ID,
                    "code": "initial_consultation",
                    "duration_minutes": 60,
                    "is_active": True,
                },
            ],
        ),
        (
            WeeklySchedule,
            [
                {
                    "id": uuid5(ident, f"weekday:{day}"),
                    "practitioner_id": ident,
                    "weekday": day,
                    "opens_at": time(9),
                    "closes_at": time(17),
                }
                for ident in PRACTITIONER_IDS
                for day in range(1, 6)
            ],
        ),
    ]
    for model, entries in rows:
        for entry in entries:
            statement = insert(model).values(**entry)
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["id"],
                    set_={key: getattr(statement.excluded, key) for key in entry if key != "id"},
                )
            )
