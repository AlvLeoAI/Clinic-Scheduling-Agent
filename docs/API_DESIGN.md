# API design and OpenAPI usage

Base `/api/v1`. JSON/Pydantic contracts, UUID identifiers, RFC3339 offset-aware timestamps and sanitized error envelope `{error:{code,message,retryable},trace_id}`. Every response carries `X-Trace-ID`. Public routes are health/catalog/session creation/availability; resource and chat routes require the owning bearer in `Authorization: Bearer <private_session_token>`.

| Method / path | Purpose |
| --- | --- |
| POST `/sessions` | `{}` → session ID, one-time private bearer, fixed expiry and trace. |
| GET `/catalog` | Synthetic clinic, practitioners and appointment types/IDs. |
| GET `/health` | Process/DB connectivity; not a production-readiness assertion. |
| GET `/availability?date=YYYY-MM-DD&practitioner_id=UUID&appointment_type_id=UUID` | Read-only valid intervals and server-derived duration/timezone. |
| POST `/proposals` | Required practitioner/type UUID, exact local_date YYYY-MM-DD and local_time HH:MM. 201 new or 200 same live tuple without TTL renewal. |
| GET `/proposals/{id}` | Owning-session authoritative snapshot/status; materializes expiry. |
| POST `/proposals/{id}/confirm` | Owning bearer + printable 1–200-character Idempotency-Key, no body or `{}`. No mutable booking fields. |
| GET `/appointments/{id}` | Owning-session actual committed appointment. |
| POST `/chat/messages` | UUID client_message_id + nonblank message ≤4000 chars; turn/message/trace and nullable authoritative proposal. |

Run the documented server, then open `http://127.0.0.1:8000/docs` or fetch `/openapi.json`. The checked-in [snapshot](openapi.json) was exported and parity-checked in original M6, and now documents the R3E.3 body-admission response. Parity was subsequently checked in accepted verification and is rechecked by R2D documentation checks; this does not imply current hosted validation. The inherited API title includes “foundation”; implemented routes/contracts are authoritative. Do not paste bearers into shared screenshots or logs.

Proposal fields include owner/clinic/practitioner/type IDs, duration, starts/ends, timezone, created/expiry/status and trace. Duration comes only from type. Full interval must fit Chicago weekdays 09:00–17:00, aligned every 30 minutes, with elapsed lead in inclusive [24 hours,90 days]. Missing/ambiguous scheduling parameters require clarification; the backend does not guess dates/practitioners/types.

Confirmation returns 201 only after committed booking/state/result. The client verifies the appointment before its CONFIRMED display. Same owning key/request replays original HTTP status/body bytes/trace, even after deadlines. Same key with changed request is 409 IDEMPOTENCY_KEY_REUSED. New key on an already confirmed proposal yields ALREADY_CONFIRMED plus its owning appointment; it cannot duplicate it.

Use the same key on network loss or retryable 503. A timeout establishes neither failure nor success. Cross-session/unknown resources are concealed as 404; expired bearer 401; expired proposal 410; superseded/conflicted 409; invalid ingress/policy 422. Policy-invalid live proposals retain PENDING; no new terminal state is invented.

Completed chat replay keeps historical message/turn/trace but refreshes existing proposal status, so whole JSON may differ. In-progress same-session turns return 409 TURN_IN_PROGRESS; changed payload with same message UUID returns MESSAGE_ID_REUSED. Failed recoverable turns resume their journal under the original UUID. These chat semantics differ intentionally from exact M3 confirmation replay. See [agent/state review](M5_RECONCILIATION.md) and [operations](OPERATIONS.md).

### Proposal provenance in chat

The R3C.1b correction preserves the existing ChatResponse and ChatFailureResponse
schemas. A successful current-turn correlated tool result may reuse an existing
same-details proposal. An attached prior proposal is explicitly labeled as previous
session state in assistant_message, or in error.message on an incomplete turn.
Failed operations are described from validated recorded tool errors. Status remains
a fresh backend projection on replay; prose is stable and confirmation instructions
are conditional on PENDING. A proposal intent without a successful result does not
claim creation. See [contract 1.2](EVALUATION_CONTRACT_V1_2.md).


## Request admission and obsolete intent recovery

All HTTP request bodies have a 65,536-byte (64 KiB) application admission limit.
Oversized declarations are rejected immediately; actual received bytes are bounded
regardless of absent, invalid or understated Content-Length. HTTP 413 uses the
existing sanitized ErrorResponse with REQUEST_TOO_LARGE and a correlated
X-Trace-ID. No oversized body reaches JSON parsing. A server may already have
allocated a large individual ASGI frame; this application does not retain it in
its admitted buffer. This is not a request-rate or slow-client deadline control.

Under the session row lock, each accepted proposal journals a stale-intent marker
for other unfinished chat turns. A previously unexecuted proposal mutation in a
marked turn returns HTTP 409 STALE_INTENT using the existing ErrorResponse. Send
a new message UUID to express a changed intention. Already recorded tool results
and completed responses remain replayable, and read-only recovery remains available.
Proposal acceptance and the markers commit or roll back together. These internal
markers never enter provider context. Confirmation semantics and the three tools
are unchanged; there is no new evaluation contract or database migration.

New turns record an internal ordering-origin item under the same session lock.
Reclaiming an old turn never adds this origin. Before an unexecuted mutation, an
unmarked legacy turn with any same-session proposal history fails closed with
HTTP 409 STALE_INTENT: its ordering cannot be verified, so a fresh message is
required. This includes terminal proposal history and may conservatively reject
a legitimate old intention whose relative order cannot be proved. No timestamp
comparison or legacy-state backfill is used. Recorded effects and completed
results still replay first; uncontested legacy recovery with no proposal history
and read-only recovery remain available. Origin items never enter provider context.
All mutation writers must use the corrected implementation; mixed-version writers
are not supported. No deployment, existing-database migration or cleanup is implied.
