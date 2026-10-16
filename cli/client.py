"""Durable client identity and direct confirmation; never infer success from a timeout."""

import json
import os
import stat
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from app.schemas.booking import AppointmentResponse, ProposalResponse
from app.schemas.chat import ChatResponse
from app.schemas.foundation import SessionResponse


class StateFile:
    def __init__(self, path, scope):
        self.path, self.scope = Path(path), scope
        self.value = {"scope": scope, "session": None, "confirmations": {}, "pending_chat": None}
        if self.path.exists() or self.path.is_symlink():
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as source:
                metadata = os.fstat(source.fileno())
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                ):
                    raise ValueError("CLI state must be an owner-only mode-0600 regular file.")
                self.value = json.load(source)
            if self.value.get("scope") != scope:
                raise ValueError("CLI state belongs to a different synthetic backend.")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".state-")
        try:
            with os.fdopen(fd, "w") as target:
                os.fchmod(target.fileno(), 0o600)
                json.dump(self.value, target)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class ClinicClient:
    def __init__(self, http, state, emit=print):
        self.http, self.state, self.emit = http, state, emit
        self.last_proposal = None

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.state.value["session"]["session_token"]}

    def session(self):
        if self.state.value["session"] is None:
            response = self.http.post("/api/v1/sessions", json={})
            response.raise_for_status()
            self.state.value["session"] = SessionResponse.model_validate(
                response.json()
            ).model_dump(mode="json")
            self.state.save()
        self.emit("Synthetic session ready; bearer is stored privately, never displayed.")

    def show_proposal(self, value):
        proposal = ProposalResponse.model_validate(value)
        self.last_proposal = str(proposal.proposal_id)
        self.emit(
            f"PROPOSAL {proposal.proposal_id}: {proposal.status}; "
            f"practitioner={proposal.practitioner_id}; type={proposal.appointment_type_id}; "
            f"duration={proposal.duration_minutes}m; {proposal.starts_at.isoformat()} to "
            f"{proposal.ends_at.isoformat()}; expires={proposal.expires_at.isoformat()}"
        )

    def chat(self, message, *, retry=False):
        pending = self.state.value["pending_chat"]
        if pending and not retry:
            self.emit("UNCERTAIN previous chat: use retry-chat to retain its client_message_id.")
            return None
        if retry and pending is None:
            self.emit("No pending chat request.")
            return None
        if not retry:
            pending = {"client_message_id": str(uuid4()), "message": message}
            self.state.value["pending_chat"] = pending
            self.state.save()
        try:
            response = self.http.post("/api/v1/chat/messages", headers=self.headers, json=pending)
            body = response.json()
        except (httpx.TransportError, ValueError):
            self.emit("UNCERTAIN chat result: retry-chat; no booking conclusion is established.")
            return None
        if response.status_code == 200:
            answer = ChatResponse.model_validate(body)
            self.state.value["pending_chat"] = None
            self.state.save()
            self.emit(answer.assistant_message)
        else:
            code = body.get("error", {}).get("code", "REQUEST_ERROR")
            self.emit(f"CHAT {response.status_code} {code}; a reply or booking is not established.")
            if response.status_code not in {409, 503}:
                self.state.value["pending_chat"] = None
                self.state.save()
        if body.get("proposal"):
            self.show_proposal(body["proposal"])
        return response

    def confirm(self, proposal_id):
        proposal_id = str(UUID(proposal_id))
        intent = self.state.value["confirmations"].setdefault(
            proposal_id, {"key": str(uuid4()), "outcome": "UNCERTAIN"}
        )
        self.state.save()  # Must be durable BEFORE sending the first request.
        try:
            response = self.http.post(
                f"/api/v1/proposals/{proposal_id}/confirm",
                headers={**self.headers, "Idempotency-Key": intent["key"]},
                json={},
            )
            body = response.json()
            code = body.get("error", {}).get("code")
            if response.status_code == 201 or code == "ALREADY_CONFIRMED":
                claimed = AppointmentResponse.model_validate(
                    body if response.status_code == 201 else body["appointment"]
                )
                verified = self.http.get(
                    f"/api/v1/appointments/{claimed.appointment_id}", headers=self.headers
                )
                if verified.status_code != 200:
                    raise ValueError("Appointment verification unavailable.")
                actual = AppointmentResponse.model_validate(verified.json())
                if (
                    actual.appointment_id != claimed.appointment_id
                    or str(actual.proposal_id) != proposal_id
                    or actual.starts_at != claimed.starts_at
                    or actual.ends_at != claimed.ends_at
                ):
                    raise ValueError("Appointment verification mismatch.")
                intent["outcome"] = "CONFIRMED"
                self.state.save()
                self.emit(
                    f"CONFIRMED verified appointment {actual.appointment_id}: "
                    f"{actual.starts_at.isoformat()} to {actual.ends_at.isoformat()}; "
                    f"trace={claimed.trace_id}"
                )
                return response
            if response.status_code >= 500:
                raise ValueError("Confirmation outcome uncertain.")
            intent["outcome"] = code or "REQUEST_ERROR"
            self.state.save()
            self.emit(f"CONFIRM {response.status_code} {intent['outcome']}; original key retained.")
            current = self.http.get(f"/api/v1/proposals/{proposal_id}", headers=self.headers)
            if current.status_code == 200:
                self.show_proposal(current.json())
            return response
        except (httpx.TransportError, ValueError):
            intent["outcome"] = "UNCERTAIN"
            self.state.save()
            self.emit(
                f"UNCERTAIN confirmation: retry confirm {proposal_id}; "
                "the same key is retained. Do not infer booking failure or success."
            )
            return None

    def dispatch(self, line):
        if line.split(maxsplit=1)[:1] == ["confirm"]:
            parts = line.split()
            if len(parts) != 2:
                raise ValueError("Use confirm <proposal_id>.")
            return self.confirm(parts[1])
        if line == "retry-chat":
            return self.chat("", retry=True)
        return self.chat(line)
