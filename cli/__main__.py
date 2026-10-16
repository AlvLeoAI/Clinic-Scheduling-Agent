"""Offline text demonstration, through FastAPI; no live-provider execution mode."""

import argparse
import hashlib
import json
import logging
import tempfile
from pathlib import Path
from uuid import UUID

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Appointment, IdempotencyRecord
from app.db.seed import PRACTITIONER_IDS, TYPE_IDS
from app.db.session import build_engine
from app.main import create_app
from cli.client import ClinicClient, StateFile
from cli.fake_provider import DemoProvider
from scripts.demo_support import NOW, ROOT, cleanup_owned, demo_settings, prepare, validate_engine


def scope(settings):
    from sqlalchemy.engine import make_url

    url = make_url(settings.database_url.get_secret_value())
    value = f"fake:{url.host}:{url.port}:{url.database}:{url.username}:{NOW.isoformat()}"
    return hashlib.sha256(value.encode()).hexdigest()


class DropOneConfirmation:
    """Demo-only transport interruption AFTER the real endpoint commits."""

    def __init__(self, client):
        self.client, self.lost = client, None

    def post(self, url, **kwargs):
        response = self.client.post(url, **kwargs)
        if url.endswith("/confirm") and self.lost is None:
            self.lost = response
            raise httpx.ReadError("Synthetic lost response after committed HTTP operation.")
        return response

    def get(self, *args, **kwargs):
        return self.client.get(*args, **kwargs)


def scripted_demo(settings, engine):
    validate_engine(settings, engine)
    transcript, owners = [], []
    provider = DemoProvider()
    app = create_app(settings, engine, clock=lambda: NOW, provider_factory=lambda: provider)
    try:
        with (
            tempfile.TemporaryDirectory(prefix="clinic-m6-cli-") as directory,
            TestClient(app) as http,
        ):
            state_path = Path(directory) / "private-state.json"
            client = ClinicClient(http, StateFile(state_path, scope(settings)), transcript.append)
            client.session()
            owner = UUID(client.state.value["session"]["session_id"])
            owners.append(owner)
            health = http.get("/api/v1/health")
            schema = http.get("/openapi.json")
            assert health.status_code == 200 and health.json()["database"] == "ok"
            assert schema.status_code == 200 and len(schema.json()["paths"]) == 9
            assert http.get("/docs").status_code == 200
            for line in [
                "catalog",
                f"availability 2030-01-09 {PRACTITIONER_IDS[0]} {TYPE_IDS[0]}",
                f"propose 2030-01-09 09:00 {PRACTITIONER_IDS[0]} {TYPE_IDS[0]}",
            ]:
                transcript.append("> " + line)
                assert client.dispatch(line).status_code == 200
            proposal_id = client.last_proposal
            provider_before = len(provider.requests)
            drop = DropOneConfirmation(http)
            client.http = drop
            transcript.append("> confirm " + proposal_id + " [synthetic response loss]")
            assert client.dispatch("confirm " + proposal_id) is None
            key = client.state.value["confirmations"][proposal_id]["key"]
            with Session(engine) as db:
                committed = db.scalar(
                    select(Appointment).where(Appointment.proposal_id == UUID(proposal_id))
                )
                assert committed is not None
                committed_id = str(committed.id)
                count_at_loss = db.scalar(
                    select(func.count())
                    .select_from(Appointment)
                    .where(Appointment.session_id == owner)
                )
                records_at_loss = db.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.session_id == owner)
                )
                assert count_at_loss == records_at_loss == 1
            restarted_engine = build_engine(settings)
            try:
                restarted_app = create_app(
                    settings, restarted_engine, clock=lambda: NOW, provider_factory=lambda: provider
                )
                with TestClient(restarted_app) as fresh_http:
                    restored = ClinicClient(
                        fresh_http, StateFile(state_path, scope(settings)), transcript.append
                    )
                    restored.session()
                    transcript.append("> confirm " + proposal_id + " [restart, same key]")
                    recovered = restored.dispatch("confirm " + proposal_id)
                    repeated = restored.dispatch("confirm " + proposal_id)
                    assert recovered.status_code == repeated.status_code == 201
                    assert recovered.content == repeated.content == drop.lost.content
                    assert recovered.json()["appointment_id"] == committed_id
                    assert restored.state.value["confirmations"][proposal_id]["key"] == key
            finally:
                restarted_engine.dispose()
            assert len(provider.requests) == provider_before
            assert client.state.value["session"]["session_token"] not in "\n".join(transcript)
            result = {
                "status": "PASS",
                "mode": "fake provider, in-process FastAPI HTTP contracts, real PostgreSQL",
                "clinic_clock": NOW.isoformat(),
                "health": "PASS",
                "openapi_paths": 9,
                "docs_http_status": 200,
                "appointment_count_at_lost_response": count_at_loss,
                "idempotency_records_at_loss": records_at_loss,
                "same_key_after_restart": True,
                "byte_identical_replay": True,
                "confirmation_provider_requests": 0,
                "appointment_id": committed_id,
                "proposal_id": proposal_id,
                "trace_id": recovered.json()["trace_id"],
                "transcript": transcript,
                "transient_demo_rows": True,
            }
    finally:
        cleanup_owned(engine, owners)
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.session_id.in_(owners))
            )
            == 0
        )
    result["owned_rows_cleaned"] = True
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Synthetic text CLI; fake provider only, no live mode."
    )
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--scripted", action="store_true")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if not args.synthetic_only:
        parser.error("--synthetic-only is required before accessing the test database.")
    if args.scripted and args.state is not None:
        parser.error("Scripted demo uses its own ephemeral private state.")
    logging.getLogger("clinic.requests").setLevel(logging.WARNING)
    engine = None
    try:
        settings = demo_settings()
        engine = prepare(settings)
        if args.scripted:
            result = scripted_demo(settings, engine)
            for line in result["transcript"]:
                print(line)
            if args.evidence:
                args.evidence.parent.mkdir(parents=True, exist_ok=True)
                args.evidence.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({k: v for k, v in result.items() if k != "transcript"}))
            return 0
        provider = DemoProvider()
        app = create_app(settings, engine, clock=lambda: NOW, provider_factory=lambda: provider)
        with TestClient(app) as http:
            client = ClinicClient(
                http, StateFile(args.state or ROOT / ".local/cli_state.json", scope(settings))
            )
            client.session()
            print(
                "Fake provider only. Commands: catalog; availability DATE PRACTITIONER_UUID "
                "TYPE_UUID; propose DATE HH:MM PRACTITIONER_UUID TYPE_UUID; "
                "confirm PROPOSAL_UUID; retry-chat; quit."
            )
            while True:
                try:
                    line = input("> ").strip()
                except EOFError:
                    break
                if line == "quit":
                    break
                if line:
                    try:
                        client.dispatch(line)
                    except ValueError:
                        print(
                            "Invalid command or server contract; no booking claim is established."
                        )
        return 0
    except Exception:
        print(
            "Demo failed safely. Check synthetic configuration and test evidence; "
            "no result is inferred."
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
