from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Appointment, ChatSession
from app.db.seed import PRACTITIONER_IDS, TYPE_IDS, seed_catalog
from app.main import create_app
from cli.__main__ import scripted_demo
from cli.client import ClinicClient, StateFile
from cli.fake_provider import DemoProvider
from scripts.demo_concurrency import run_demo
from scripts.demo_support import NOW, cleanup_owned

pytestmark = [pytest.mark.postgres, pytest.mark.api]


@pytest.fixture
def settings(engine):
    with Session(engine) as db, db.begin():
        seed_catalog(db)
    return Settings(
        _env_file=None,
        database_url=engine.url.render_as_string(hide_password=False),
        enable_live_openai=False,
        openai_model="synthetic-offline-demo",
    )


def test_cli_real_commit_loss_restart_and_verified_replay(engine, settings):
    result = scripted_demo(settings, engine)
    assert result["status"] == "PASS" and result["same_key_after_restart"]
    assert result["confirmation_provider_requests"] == 0 and result["owned_rows_cleaned"]


def test_concurrent_demo_actual_exclusion_and_verified_alternatives(engine, settings):
    result = run_demo(settings, engine)
    assert result["responses"] == [201, 409] and len(set(result["confirmation_backend_pids"])) == 2
    assert result["conflict"]["sqlstate"] == "23P01" and result["appointment_count_verified"] == 1
    assert len(result["alternative_slots_verified"]) == 14 and result["owned_rows_cleaned"]


def test_concurrency_demo_refuses_existing_booking_without_reset(engine, settings):
    owner = None
    app = create_app(settings, engine, clock=lambda: NOW)
    try:
        with TestClient(app) as http:
            session = http.post("/api/v1/sessions", json={}).json()
            owner = UUID(session["session_id"])
            headers = {"Authorization": "Bearer " + session["session_token"]}
            proposal = http.post(
                "/api/v1/proposals",
                headers=headers,
                json={
                    "local_date": "2030-01-09",
                    "local_time": "09:00",
                    "practitioner_id": str(PRACTITIONER_IDS[0]),
                    "appointment_type_id": str(TYPE_IDS[0]),
                },
            ).json()
            booked = http.post(
                f"/api/v1/proposals/{proposal['proposal_id']}/confirm",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={},
            )
            assert booked.status_code == 201
        with Session(engine) as db:
            before = db.scalar(select(func.count()).select_from(ChatSession))
        with pytest.raises(ValueError):
            run_demo(settings, engine)
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(ChatSession)) == before
            assert db.scalar(select(func.count()).select_from(Appointment)) == 1
            assert db.get(Appointment, UUID(booked.json()["appointment_id"])) is not None
    finally:
        cleanup_owned(engine, [owner] if owner else [])


@pytest.mark.parametrize("terminal", ["EXPIRED", "SUPERSEDED", "CONFLICTED"])
def test_cli_terminal_outcomes_are_backend_projections(engine, settings, tmp_path, terminal):
    provider, output, owners = DemoProvider(), [], []
    now = [NOW]
    app = create_app(settings, engine, clock=lambda: now[0], provider_factory=lambda: provider)
    try:
        with TestClient(app) as http:
            client = ClinicClient(
                http, StateFile(tmp_path / "state.json", "synthetic"), output.append
            )
            client.session()
            owners.append(UUID(client.state.value["session"]["session_id"]))
            assert (
                client.dispatch(
                    f"propose 2030-01-09 09:00 {PRACTITIONER_IDS[0]} {TYPE_IDS[0]}"
                ).status_code
                == 200
            )
            original = client.last_proposal
            args = {
                "local_date": "2030-01-09",
                "local_time": "10:00",
                "practitioner_id": str(PRACTITIONER_IDS[0]),
                "appointment_type_id": str(TYPE_IDS[0]),
            }
            if terminal == "EXPIRED":
                now[0] += timedelta(seconds=601)
            elif terminal == "SUPERSEDED":
                assert (
                    http.post("/api/v1/proposals", headers=client.headers, json=args).status_code
                    == 201
                )
            else:
                other = http.post("/api/v1/sessions", json={}).json()
                owners.append(UUID(other["session_id"]))
                headers = {"Authorization": "Bearer " + other["session_token"]}
                proposal = http.post(
                    "/api/v1/proposals", headers=headers, json={**args, "local_time": "09:00"}
                ).json()
                assert (
                    http.post(
                        f"/api/v1/proposals/{proposal['proposal_id']}/confirm",
                        headers={**headers, "Idempotency-Key": str(uuid4())},
                        json={},
                    ).status_code
                    == 201
                )
            count = len(provider.requests)
            response = client.dispatch("confirm " + original)
            assert response.status_code == (410 if terminal == "EXPIRED" else 409)
            assert any(f": {terminal};" in line for line in output)
            assert len(provider.requests) == count
            with Session(engine) as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(Appointment)
                        .where(Appointment.session_id == owners[0])
                    )
                    == 0
                )
    finally:
        cleanup_owned(engine, owners)
