"""HTTP client for the Streamlit UI. Uses httpx only, so it is testable without Streamlit.

The UI never talks to the database: every read and write goes through the API, and
booking happens only through POST /proposals/{id}/confirm.
"""

from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID, uuid4

import httpx

ERROR_MESSAGES = {
    "SLOT_TAKEN": "That slot was just taken. Check availability again and pick another.",
    "PROPOSAL_EXPIRED": "This proposal has expired. Ask for a new one.",
    "PROPOSAL_SUPERSEDED": "A newer proposal replaced this one. Confirm the latest instead.",
    "AGENT_PROVIDER_DISABLED": "Chat is disabled on this server: no agent provider is set.",
    "UNAUTHORIZED": "Your session has expired. A new one has been started.",
    "IDEMPOTENCY_KEY_REUSED": "This confirmation key was already used for another request.",
}


def _strings(value: object, *names: str) -> dict[str, str]:
    """The named fields of a JSON object, each a string; ValueError for any other shape."""
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    fields = {name: value.get(name) for name in names}
    if not all(isinstance(field, str) for field in fields.values()):
        raise ValueError(f"expected string fields {names}")
    return fields


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool, body: dict):
        super().__init__(f"{status} {code}")
        self.status, self.code, self.message = status, code, message
        self.retryable, self.body = retryable, body

    @property
    def user_message(self) -> str:
        if self.code in ERROR_MESSAGES:
            return ERROR_MESSAGES[self.code]
        if self.retryable:
            return "The service is temporarily unavailable. Retry to resend the same request."
        return self.message


def _unreadable_confirm(status: int) -> ApiError:
    # A confirm answer that cannot be read: it may have booked, so it is never final.
    unreadable = "The API returned an unexpected response."
    return ApiError(status, "UNEXPECTED_RESPONSE", unreadable, True, {})


@dataclass(frozen=True)
class Info:
    agent_provider: str
    min_notice_hours: int
    max_horizon_days: int


@dataclass(frozen=True)
class SessionToken:
    session_id: UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class Option:
    id: UUID
    label: str


@dataclass(frozen=True)
class Catalog:
    clinic_name: str
    timezone: str
    practitioners: list[Option]
    appointment_types: list[Option]


@dataclass(frozen=True)
class Slot:
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class Proposal:
    proposal_id: UUID
    practitioner_id: UUID
    appointment_type_id: UUID
    starts_at: datetime
    ends_at: datetime
    expires_at: datetime
    status: str

    @classmethod
    def from_body(cls, body: dict) -> "Proposal":
        return cls(
            proposal_id=UUID(body["proposal_id"]),
            practitioner_id=UUID(body["practitioner_id"]),
            appointment_type_id=UUID(body["appointment_type_id"]),
            starts_at=datetime.fromisoformat(body["starts_at"]),
            ends_at=datetime.fromisoformat(body["ends_at"]),
            expires_at=datetime.fromisoformat(body["expires_at"]),
            status=body["status"],
        )

    def seconds_left(self, now: datetime) -> int:
        return max(0, int((self.expires_at - now).total_seconds()))


@dataclass(frozen=True)
class ChatReply:
    assistant_message: str
    proposal: Proposal | None
    provider: str | None


@dataclass(frozen=True)
class Appointment:
    appointment_id: UUID
    proposal_id: UUID
    starts_at: datetime
    ends_at: datetime
    already_confirmed: bool = False

    @classmethod
    def from_body(cls, body: object, *, already_confirmed: bool = False) -> "Appointment":
        """Raises only ValueError, for a missing field or a wrong type or format."""
        fields = _strings(body, "appointment_id", "proposal_id", "starts_at", "ends_at")
        return cls(
            appointment_id=UUID(fields["appointment_id"]),
            proposal_id=UUID(fields["proposal_id"]),
            starts_at=datetime.fromisoformat(fields["starts_at"]),
            ends_at=datetime.fromisoformat(fields["ends_at"]),
            already_confirmed=already_confirmed,
        )


def confirmation_key(store: MutableMapping[str, str], proposal_id: UUID) -> str:
    """One Idempotency-Key per proposal, kept in `store` (Streamlit's session_state).

    Reruns and double clicks reuse the key, so the server returns the same appointment
    instead of booking twice.
    """
    return store.setdefault(str(proposal_id), str(uuid4()))


class ClinicApi:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 45.0,
    ):
        # The timeout exceeds the server's default provider timeout (30 s).
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"), transport=transport, timeout=timeout
        )

    def close(self) -> None:
        self.http.close()

    def _request(
        self, method: str, path: str, token: str | None = None, **kwargs
    ) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self.http.request(method, f"/api/v1{path}", headers=headers, **kwargs)
        except httpx.TransportError:
            unreachable = "The API could not be reached."
            raise ApiError(503, "API_UNREACHABLE", unreachable, True, {}) from None
        if response.status_code >= 400:
            # The envelope is {"error": {"code": str, "message": str, "retryable": bool}};
            # anything else (bad JSON included) is UNEXPECTED_RESPONSE with the same status.
            try:
                body = response.json()
                envelope = body.get("error") if isinstance(body, dict) else None
                error = _strings(envelope, "code", "message")
            except ValueError:
                raise ApiError(
                    response.status_code,
                    "UNEXPECTED_RESPONSE",
                    "The API returned an unexpected response.",
                    response.status_code >= 500,
                    {},
                ) from None
            retryable = envelope.get("retryable") is True
            raise ApiError(response.status_code, error["code"], error["message"], retryable, body)
        return response

    def info(self) -> Info:
        body = self._request("GET", "/info").json()
        return Info(body["agent_provider"], body["min_notice_hours"], body["max_horizon_days"])

    def create_session(self) -> SessionToken:
        body = self._request("POST", "/sessions", json={}).json()
        return SessionToken(
            UUID(body["session_id"]),
            body["session_token"],
            datetime.fromisoformat(body["expires_at"]),
        )

    def catalog(self) -> Catalog:
        body = self._request("GET", "/catalog").json()
        return Catalog(
            clinic_name=body["clinic"]["name"],
            timezone=body["clinic"]["timezone"],
            practitioners=[Option(UUID(p["id"]), p["display_name"]) for p in body["practitioners"]],
            appointment_types=[
                Option(UUID(t["id"]), f"{t['code']} ({t['duration_minutes']} min)")
                for t in body["appointment_types"]
            ],
        )

    def availability(self, day: date, practitioner_id: UUID, type_id: UUID) -> list[Slot]:
        params = {
            "date": day.isoformat(),
            "practitioner_id": str(practitioner_id),
            "appointment_type_id": str(type_id),
        }
        body = self._request("GET", "/availability", params=params).json()
        return [
            Slot(datetime.fromisoformat(s["starts_at"]), datetime.fromisoformat(s["ends_at"]))
            for s in body["slots"]
        ]

    def chat(self, token: str, message: str, client_message_id: UUID) -> ChatReply:
        # Retrying a failed turn must reuse client_message_id so the server replays it.
        response = self._request(
            "POST",
            "/chat/messages",
            token,
            json={"client_message_id": str(client_message_id), "message": message},
        )
        body = response.json()
        proposal = body.get("proposal")
        return ChatReply(
            assistant_message=body["assistant_message"],
            proposal=Proposal.from_body(proposal) if proposal else None,
            provider=response.headers.get("X-Agent-Provider"),
        )

    def proposal(self, token: str, proposal_id: UUID) -> Proposal:
        return Proposal.from_body(self._request("GET", f"/proposals/{proposal_id}", token).json())

    def confirm(self, token: str, proposal_id: UUID, idempotency_key: str) -> Appointment:
        try:
            response = self._request(
                "POST",
                f"/proposals/{proposal_id}/confirm",
                token,
                headers={"Idempotency-Key": idempotency_key},
                json={},
            )
        except ApiError as error:
            if error.code != "ALREADY_CONFIRMED":
                raise
            try:
                appointment = error.body.get("appointment")
                return Appointment.from_body(appointment, already_confirmed=True)
            except ValueError:
                raise _unreadable_confirm(error.status) from None
        try:
            return Appointment.from_body(response.json())
        except ValueError:
            # A success status with an unreadable body: it may have booked.
            raise _unreadable_confirm(response.status_code) from None
