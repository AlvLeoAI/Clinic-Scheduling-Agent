"""Reproducible synthetic evaluations over real PostgreSQL and mocked Responses HTTP."""

import argparse
import copy
import hashlib
import json
import logging
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, Lock
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.agent.provider import HttpResponsesProvider
from app.agent.replies import reply_format
from app.agent.tools import tool_definitions
from app.core.config import Settings
from app.db.models import (
    Appointment,
    AppointmentType,
    BookingProposal,
    ChatSession,
    ChatTurn,
    Clinic,
    ConversationItem,
    IdempotencyRecord,
    Practitioner,
)
from app.db.safety import require_demo_database
from app.db.seed import seed_catalog
from app.db.session import build_engine
from app.main import create_app
from app.services.booking import BookingService
from app.services.chat import INSTRUCTIONS
from evaluations.contracts import Dataset
from evaluations.oracle import instant, slots
from evaluations.scoring import CONTRACT_VERSIONS, contract_metadata, select_contract

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluations/datasets/scheduling_v1.json"


def load_dataset(path=DATASET):
    return Dataset.model_validate_json(Path(path).read_text())


def prompt_hash(instructions, tools, text_format):
    value = {"instructions": instructions, "tools": tools, "text": text_format}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FixtureProvider:
    """Capture fixture decisions BEFORE application validation; use the actual REST adapter."""

    def __init__(self, case, settings):
        self.case = case
        self.queues = {alias: deque(rows) for alias, rows in case.script.items()}
        self.lock, self.requests, self.outputs = Lock(), [], []
        self.message_ids = {}
        self.raw_calls, self.raw_plans, self.errors = [], [], []
        self.barrier = Barrier(2) if case.exercise == "isolation_restart" else None
        self.first = set()
        # Always attach MockTransport. No code path can construct a live client here.
        config = settings.model_copy(update={"enable_live_openai": True})
        self.adapter = HttpResponsesProvider(config, httpx.MockTransport(self.transport))

    def respond(self, payload):
        return self.adapter.respond(payload)

    def transport(self, request):
        assert request.url == httpx.URL("https://api.openai.com/v1/responses")
        payload = json.loads(request.content)
        latest = [item["content"] for item in payload["input"] if item.get("role") == "user"][-1]
        alias = next(row.session for row in self.case.input if row.message == latest)
        with self.lock:
            self.requests.append({"session": alias, "payload": payload})
            if not self.queues[alias]:
                raise AssertionError("Synthetic response script exhausted.")
            step = self.queues[alias].popleft()
            index = len(self.requests)
            synchronize = self.barrier is not None and alias not in self.first
            self.first.add(alias)
        if synchronize:
            self.barrier.wait(timeout=5)
        if "error" in step:
            self.errors.append({"session": alias, "kind": step["error"]})
            if step["error"] == "timeout":
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(500, json={"error": {"message": "synthetic provider error"}})
        call_id = f"eval_{self.case.id}_{alias}_{index}"
        if "tool" in step:
            output = [
                {
                    "type": "reasoning",
                    "id": "rs_" + call_id,
                    "summary": [],
                    "encrypted_content": "opaque-synthetic-context",
                },
                {
                    "type": "function_call",
                    "id": "fc_" + call_id,
                    "call_id": call_id,
                    "name": step["tool"],
                    "arguments": json.dumps(step["arguments"]),
                    "status": "completed",
                },
            ]
            self.raw_calls.append(
                {
                    "session": alias,
                    "name": step["tool"],
                    "arguments": step["arguments"],
                    "call_id": call_id,
                    "client_message_id": self.message_ids[(alias, latest)],
                }
            )
        else:
            value = step.get(
                "raw_text",
                {"kind": step.get("reply"), "missing_fields": step.get("missing_fields", [])},
            )
            self.raw_plans.append(
                {
                    "session": alias,
                    "value": copy.deepcopy(value),
                    "client_message_id": self.message_ids[(alias, latest)],
                }
            )
            value = value if isinstance(value, str) else json.dumps(value)
            output = [
                {
                    "type": "message",
                    "id": "msg_" + call_id,
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": value, "annotations": []}],
                }
            ]
        response = {
            "id": "resp_" + call_id,
            "object": "response",
            "status": "completed",
            "model": "synthetic-offline-m5",
            "output": output,
            "usage": None,
        }
        self.outputs.append(copy.deepcopy(response))
        return httpx.Response(200, json=response)


class CaseRun:
    def __init__(self, case, dataset, engine):
        self.case, self.dataset, self.engine = case, dataset, engine
        self.clock = Clock(instant(dataset.clock))
        self.settings = Settings(
            _env_file=None,
            database_url=engine.url.render_as_string(hide_password=False),
            openai_model="synthetic-offline-m5",
            openai_api_key="synthetic-m5-credential",
            enable_live_openai=False,
        )
        self.provider = FixtureProvider(case, self.settings)
        self.ids, self.bearers = {}, {}
        self.responses, self.confirmations, self.provenance = [], [], []
        self.recovery_ok, self.race = True, None

    @contextmanager
    def client(self, engine=None):
        app = create_app(self.settings, engine or self.engine, self.clock, lambda: self.provider)
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client

    def setup(self, client):
        with Session(self.engine) as db:
            seed_catalog(db)
            db.commit()
            self.catalog_truth = {
                "timezone": db.scalar(select(Clinic.timezone).order_by(Clinic.id).limit(1)),
                "practitioners": [
                    {"id": str(r.id), "name": r.display_name}
                    for r in db.scalars(
                        select(Practitioner)
                        .where(Practitioner.is_active.is_(True))
                        .order_by(Practitioner.id)
                    )
                ],
                "types": [
                    {"id": str(r.id), "code": r.code, "duration": r.duration_minutes}
                    for r in db.scalars(
                        select(AppointmentType)
                        .where(AppointmentType.is_active.is_(True))
                        .order_by(AppointmentType.id)
                    )
                ],
            }
        for alias in self.case.initial_db_state["sessions"]:
            response = client.post("/api/v1/sessions", json={})
            assert response.status_code == 201
            self.ids[alias] = response.json()["session_id"]
            self.bearers[alias] = {"Authorization": "Bearer " + response.json()["session_token"]}
        if self.case.initial_db_state["occupied_09_00"]:
            row = self.propose(client, "B")
            self.confirm(client, "B", row["proposal_id"], provenance="initial fixture")

    def args(self, **changes):
        return {
            "local_date": "2030-01-09",
            "local_time": "09:00",
            "practitioner_id": self.dataset.catalog["practitioners"][0],
            "appointment_type_id": next(iter(self.dataset.catalog["types"])),
            **changes,
        }

    def propose(self, client, alias, **changes):
        response = client.post(
            "/api/v1/proposals", headers=self.bearers[alias], json=self.args(**changes)
        )
        assert response.status_code == 201
        return response.json()

    def confirm(self, client, alias, proposal_id, provenance="explicit post-chat action"):
        response = client.post(
            f"/api/v1/proposals/{proposal_id}/confirm",
            headers={**self.bearers[alias], "Idempotency-Key": str(uuid4())},
            json={},
        )
        if response.status_code == 201:
            self.confirmations.append(
                {
                    "appointment_id": response.json()["appointment_id"],
                    "session": alias,
                    "provenance": provenance,
                }
            )
        return response

    def snapshot(self):
        aliases = {ident: alias for alias, ident in self.ids.items()}
        result = {"proposals": [], "appointments": []}
        with Session(self.engine) as db:
            for model, key in [(BookingProposal, "proposals"), (Appointment, "appointments")]:
                for row in db.scalars(
                    select(model)
                    .where(model.session_id.in_([UUID(v) for v in self.ids.values()]))
                    .order_by(model.id)
                ):
                    value = {
                        "id": str(row.id),
                        "session": aliases[str(row.session_id)],
                        "practitioner_id": str(row.practitioner_id),
                        "starts_at": row.starts_at.isoformat(),
                        "ends_at": row.ends_at.isoformat(),
                        "duration_minutes": row.duration_minutes,
                    }
                    if key == "proposals":
                        value.update(
                            status=row.status,
                            appointment_type_id=str(row.appointment_type_id),
                            expires_at=row.expires_at.isoformat(),
                            source_turn_id=str(row.source_turn_id) if row.source_turn_id else None,
                        )
                    else:
                        value["proposal_id"] = str(row.proposal_id)
                    result[key].append(value)
        return result

    def chat(self, client, message, *, ident=None, phase="initial"):
        ident = ident or uuid4()
        self.provider.message_ids[(message.session, message.message)] = str(ident)
        response = client.post(
            "/api/v1/chat/messages",
            headers=self.bearers[message.session],
            json={"client_message_id": str(ident), "message": message.message},
        )
        body = response.json()
        assert response.headers["X-Trace-ID"] == body["trace_id"]
        evidence = {
            "session": message.session,
            "status": response.status_code,
            "body": body,
            "phase": phase,
            "client_message_id": str(ident),
            "snapshot": self.snapshot(),
        }
        self.responses.append(evidence)
        return evidence, ident

    def journal(self):
        with Session(self.engine) as db:
            rows = db.scalars(
                select(ConversationItem)
                .where(ConversationItem.session_id.in_([UUID(v) for v in self.ids.values()]))
                .order_by(ConversationItem.created_at, ConversationItem.sequence)
            ).all()
            calls = {
                (r.turn_id, r.call_id): r.payload for r in rows if r.item_type == "function_call"
            }
            outputs = [
                {
                    "session": next(
                        alias for alias, ident in self.ids.items() if ident == str(r.session_id)
                    ),
                    "name": calls[(r.turn_id, r.call_id)]["name"],
                    "arguments": json.loads(calls[(r.turn_id, r.call_id)]["arguments"]),
                    "call_id": r.call_id,
                    "turn_id": str(r.turn_id),
                    "value": json.loads(r.payload["output"]),
                }
                for r in rows
                if r.item_type == "function_call_output"
            ]
            historical = [
                {"turn_id": str(r.turn_id), "body": r.payload}
                for r in rows
                if r.item_type == "chat_result"
            ]
            return outputs, historical

    def conflict(self, client, first):
        other = self.propose(client, "B")
        barrier, inserted = Barrier(2), Event()
        pids, violations = [], []
        original = BookingService._insert_appointment

        def coordinated(service, row, now):
            pids.append(service.db.scalar(text("SELECT pg_backend_pid()")))
            barrier.wait(timeout=5)
            if str(row.session_id) == self.ids["B"]:
                value = original(service, row, now)
                inserted.set()
                return value
            assert inserted.wait(timeout=5)
            try:
                return original(service, row, now)
            except IntegrityError as exc:
                violations.append(
                    {"sqlstate": exc.orig.sqlstate, "constraint": exc.orig.diag.constraint_name}
                )
                raise

        with (
            patch.object(BookingService, "_insert_appointment", coordinated),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            a = pool.submit(self.confirm, client, "A", first["body"]["proposal"]["proposal_id"])
            b = pool.submit(self.confirm, client, "B", other["proposal_id"])
            results = [a.result(timeout=10), b.result(timeout=10)]
        assert [r.status_code for r in results] == [409, 201]
        assert len(set(pids)) == 2 and violations == [
            {"sqlstate": "23P01", "constraint": "appointments_no_overlap"}
        ]
        self.race = {
            "postgres_backend_pids": pids,
            "violation": violations[0],
            "statuses": [409, 201],
        }

    def exercise(self, client):
        message = self.case.input[0]
        if self.case.exercise == "isolation_restart":
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.chat, client, value) for value in self.case.input[:2]]
                for future in futures:
                    future.result(timeout=10)
            restarted = build_engine(self.settings)
            try:
                with self.client(restarted) as new:
                    self.chat(new, self.case.input[2])
            finally:
                restarted.dispose()
            return
        first, ident = self.chat(client, message)
        effect_count = len(self.journal()[0])
        if self.case.exercise == "retry":
            assert first["status"] == 503 and len(self.snapshot()["proposals"]) == 1
            restarted = build_engine(self.settings)
            try:
                with self.client(restarted) as new:
                    current, _ = self.chat(new, message, ident=ident, phase="retry")
            finally:
                restarted.dispose()
            self.recovery_ok &= (
                current["body"]["turn_id"] == first["body"]["turn_id"]
                and current["body"]["proposal"]["proposal_id"]
                == first["body"]["proposal"]["proposal_id"]
            )
            self.recovery_ok &= len(self.journal()[0]) == effect_count
        elif self.case.exercise in {"expired", "superseded", "confirmed", "conflict"}:
            if self.case.exercise == "expired":
                self.clock.now += timedelta(seconds=601)
            elif self.case.exercise == "superseded":
                self.propose(client, "A", local_time="10:00")
            elif self.case.exercise == "confirmed":
                assert (
                    self.confirm(client, "A", first["body"]["proposal"]["proposal_id"]).status_code
                    == 201
                )
            else:
                self.conflict(client, first)
            request_count = len(self.provider.requests)
            current, _ = self.chat(client, message, ident=ident, phase="replay")
            expected_status = {
                "expired": "EXPIRED",
                "superseded": "SUPERSEDED",
                "confirmed": "CONFIRMED",
                "conflict": "CONFLICTED",
            }[self.case.exercise]
            self.recovery_ok &= current["body"]["proposal"]["status"] == expected_status
            self.recovery_ok &= (
                len(self.provider.requests) == request_count
                and len(self.journal()[0]) == effect_count
            )
            self.recovery_ok &= all(
                current["body"][field] == first["body"][field]
                for field in ("assistant_message", "turn_id", "trace_id")
            )
            self.recovery_ok &= all(
                current["body"]["proposal"][f] == first["body"]["proposal"][f]
                for f in ("proposal_id", "starts_at", "ends_at", "expires_at")
            )

    def observation(self, initial):
        outputs, historical = self.journal()
        isolation = all(
            all(
                other.message not in json.dumps(request["payload"]["input"])
                for other in self.case.input
                if other.session != request["session"]
            )
            for request in self.provider.requests
        )
        # Independently derive grounded availability times, not from generated prose.
        times = set()
        intervals = []
        for output in outputs:
            if output["name"] == "check_availability" and output["value"].get("ok"):
                valid_slots = slots(
                    output["arguments"],
                    self.dataset.catalog,
                    instant(self.dataset.clock),
                    initial["appointments"],
                )
                intervals.append({"session": output["session"], "slots": valid_slots})
                for interval in valid_slots:
                    times.update(interval.values())
        return {
            "initial": initial,
            "final": self.snapshot(),
            "responses": self.responses,
            "historical_turn_results": historical,
            "raw_calls": self.provider.raw_calls,
            "raw_plans": self.provider.raw_plans,
            "provider_errors": self.provider.errors,
            "tool_outputs": outputs,
            "explicit_confirmations": self.confirmations,
            "isolation_ok": isolation,
            "recovery_ok": self.recovery_ok,
            "catalog_ids": self.dataset.catalog["practitioners"]
            + list(self.dataset.catalog["types"]),
            "grounded_times": sorted(times),
            "grounded_intervals": intervals,
            "catalog_truth": self.catalog_truth,
            "session_ids": self.ids,
            "race": self.race,
        }

    def cleanup(self):
        with Session(self.engine) as db:
            ids = [UUID(v) for v in self.ids.values()]
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
            db.commit()


def run_case(case, dataset, engine, *, evaluation_contract="1.0"):
    grade, _ = select_contract(evaluation_contract)
    run = CaseRun(case, dataset, engine)
    try:
        with run.client() as client:
            run.setup(client)
            initial = run.snapshot()
            run.exercise(client)
            obs = run.observation(initial)
        result = grade(case, obs, dataset.catalog, dataset.clock)
        result["evaluation_contract_version"] = evaluation_contract
        for response in run.provider.outputs:
            for item in response["output"]:
                if item["type"] == "function_call":
                    assert set(item) == {"type", "id", "call_id", "name", "arguments", "status"}
        requests = []
        for request in run.provider.requests:
            payload = request["payload"]
            calls = {x["call_id"] for x in payload["input"] if x.get("type") == "function_call"}
            outputs = {
                x["call_id"] for x in payload["input"] if x.get("type") == "function_call_output"
            }
            assert calls == outputs
            assert payload["store"] is False and payload["parallel_tool_calls"] is False
            assert payload["include"] == ["reasoning.encrypted_content"]
            assert all(
                t["strict"] is True and t["parameters"]["additionalProperties"] is False
                for t in payload["tools"]
            )
            assert all(
                set(t["parameters"]["required"]) == set(t["parameters"]["properties"])
                for t in payload["tools"]
            )
            assert all(
                x.get("encrypted_content") == "opaque-synthetic-context"
                for x in payload["input"]
                if x.get("type") == "reasoning"
            )
            requests.append(
                {
                    "session": request["session"],
                    "call_ids": sorted(calls),
                    "input_chars": len(json.dumps(payload["input"], ensure_ascii=False)),
                    "item_types": [i.get("type", i.get("role")) for i in payload["input"]],
                    "prompt_sha256": prompt_hash(
                        payload["instructions"], payload["tools"], payload["text"]
                    ),
                }
            )
        result["evidence"] = {
            **obs,
            "provider_requests": requests,
            "actual_usage": None,
            "trace_ids": sorted({r["body"]["trace_id"] for r in obs["responses"]}),
        }
        return result
    finally:
        run.cleanup()


def run_dataset(engine, *, evaluation_contract="1.0"):
    metadata = contract_metadata(evaluation_contract)
    dataset = load_dataset()
    cases = [
        run_case(case, dataset, engine, evaluation_contract=evaluation_contract)
        for case in dataset.cases
    ]
    layers = {
        name: dict(Counter(c["layers"][name]["verdict"] for c in cases))
        for name in ("raw_model", "backend", "user_visible")
    }
    return {
        **metadata,
        "dataset_version": dataset.version,
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "prompt_version": dataset.prompt_version,
        "prompt_sha256": prompt_hash(
            INSTRUCTIONS
            + "Current UTC instant: "
            + dataset.clock
            + ". Clinic timezone: America/Chicago.",
            tool_definitions(),
            reply_format(),
        ),
        "prompt_source": "Instructions with fixed clock, tool definitions and strict reply schema.",
        "renderer_sha256": hashlib.sha256((ROOT / "app/agent/replies.py").read_bytes()).hexdigest(),
        "grader_sha256": metadata["scorer_sha256"],
        "clock": dataset.clock,
        "provider": {
            "kind": "httpx.MockTransport through unchanged Responses REST adapter",
            "model": "synthetic-offline-m5",
            "timeout_seconds": 30,
            "max_output_tokens": 2048,
            "turn_lease_seconds": 90,
            "context_completed_turns": 8,
            "context_characters": 24000,
            "tool_call_limit": 5,
            "store": False,
            "parallel_tool_calls": False,
            "actual_usage": None,
        },
        "agent_live": "NOT RUN",
        "case_verdict": "PASS" if all(c["verdict"] == "PASS" for c in cases) else "FAIL",
        "layers": layers,
        "cases": cases,
    }


def write_reports(result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "M5_agent_cases.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# M5 synthetic offline case results",
        "",
        "Scripted fixtures exercise agent plumbing and graders; they do not measure model quality.",
        "Case PASS means the declared disposition matched. Raw FAILs stay FAIL "
        "even when backend enforcement and the visible response PASS.",
        "",
        f"Dataset {result['dataset_version']}: `{result['dataset_sha256']}`",
        f"Prompt {result['prompt_version']}: `{result['prompt_sha256']}`",
        f"Evaluation contract {result['evaluation_contract_version']}: "
        f"{result['scorer_version']} / `{result['scorer_sha256']}`",
        "Provider: REST adapter + httpx.MockTransport; model synthetic-offline-m5; "
        "timeout 30s; actual token usage unavailable/null.",
        "AGENT LIVE EVALS: NOT RUN. No live runner is implemented.",
        "",
        "| Case | Fixture gate | Raw model | Backend | Visible | Rationale / evidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in result["cases"]:
        layers = c["layers"]
        failure = [
            name
            for name, value in layers["raw_model"]["checks"].items()
            if value["verdict"] != "PASS"
        ]
        lines.append(
            f"| {c['case_id']} | {c['verdict']} | {layers['raw_model']['verdict']} "
            f"| {layers['backend']['verdict']} | {layers['user_visible']['verdict']} "
            f"| Raw: {', '.join(failure) or 'contract matched'}; "
            f"trace {c['evidence']['trace_ids'][0]} |"
        )
    (directory / "M5_agent_summary.md").write_text("\n".join(lines) + "\n")


def main():
    logging.getLogger("clinic.requests").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(
        description="Offline synthetic evaluations only; no live runner."
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/evidence")
    parser.add_argument("--evaluation-contract", choices=CONTRACT_VERSIONS, default="1.0")
    args = parser.parse_args()
    settings = Settings()
    if settings.test_database_url is None:
        parser.error("TEST_DATABASE_URL is required; no SQLite/live fallback.")
    url = settings.test_database_url.get_secret_value()
    require_demo_database(url, test_only=True)
    engine = build_engine(Settings(_env_file=None, database_url=url))
    try:
        config = Config(str(ROOT / "alembic.ini"))
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        result = run_dataset(engine, evaluation_contract=args.evaluation_contract)
        write_reports(result, args.output_dir)
        print(
            json.dumps(
                {
                    "agent_offline_fixture_gate": result["case_verdict"],
                    "cases": len(result["cases"]),
                    "layers": result["layers"],
                    "agent_live": "NOT RUN",
                }
            )
        )
        return 0 if result["case_verdict"] == "PASS" else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
