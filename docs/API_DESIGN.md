# API design

Base path `/api/v1`. JSON contracts are Pydantic models with UUID identifiers and
offset-aware RFC 3339 timestamps. Errors use one sanitized envelope,
`{error: {code, message, retryable}, trace_id}`, that never echoes request input.
Every response carries `X-Trace-ID`. Health, catalog, session creation and
availability are public; proposal, appointment and chat routes require the owning
session's bearer token.

| Method and path | Purpose |
| --- | --- |
| POST `/sessions` | `{}` returns a session ID, a one-time bearer token (24-hour fixed expiry) and a trace ID. |
| GET `/catalog` | Synthetic clinic, practitioners and appointment types with their IDs. |
| GET `/health` | Process and database connectivity. |
| GET `/availability?date=YYYY-MM-DD&practitioner_id=UUID&appointment_type_id=UUID` | Read-only valid intervals; duration and timezone come from the server. |
| POST `/proposals` | Practitioner and type UUIDs, `local_date` (YYYY-MM-DD) and `local_time` (HH:MM). 201 for a new proposal; 200 for the same live details, without renewing its TTL. |
| GET `/proposals/{id}` | Authoritative snapshot and status for the owning session. |
| POST `/proposals/{id}/confirm` | Requires an `Idempotency-Key` header (1–200 printable characters); body empty or `{}`. Booking fields cannot be changed here. |
| GET `/appointments/{id}` | The committed appointment for the owning session. |
| POST `/chat/messages` | UUID `client_message_id` and a non-blank message up to 4,000 characters; returns the turn, the rendered assistant message, trace and the current proposal if any. |

Run the server (see [testing](../TESTING.md#running-the-server)) and open
`http://127.0.0.1:8000/docs`, or use the checked-in [OpenAPI snapshot](openapi.json);
`scripts/check_docs.py` verifies it matches the app. The API title still says
"foundation"; the routes and contracts above are authoritative.

## Proposals

A proposal records owner, clinic, practitioner, type, duration, start, end, timezone,
creation time, expiry and status. Duration comes only from the appointment type. The
whole interval must fit the Chicago weekday schedule (09:00–17:00) on the 30-minute
grid, with lead time between 24 hours and 90 days inclusive. Proposals expire ten
minutes after creation and do not reserve the interval. Status moves one way from
PENDING to CONFIRMED, CONFLICTED, EXPIRED or SUPERSEDED.

## Confirmation and idempotency

Confirmation returns 201 only after the appointment, the proposal status and the
idempotent result have committed together.

| Situation | Response |
| --- | --- |
| Same key, same request | Replays the original status, body bytes and trace, even after expiry. |
| Same key, different proposal | 409 `IDEMPOTENCY_KEY_REUSED`. |
| New key on an already confirmed proposal | 409 `ALREADY_CONFIRMED` with the existing appointment; never a duplicate. |
| Slot taken by a concurrent confirmation | 409 `SLOT_TAKEN`; the proposal becomes CONFLICTED. |
| Expired proposal | 410 `PROPOSAL_EXPIRED`. |
| Superseded proposal | 409 `PROPOSAL_SUPERSEDED`. |
| Policy no longer satisfied | 422 `BUSINESS_RULE_VIOLATION`; the proposal stays PENDING. |
| Another session's or unknown resource | 404 (existence is not revealed). |
| Missing or expired bearer | 401. |

After a network error or a retryable 503, retry with the same key. A timeout means
the outcome is unknown, not that it failed or succeeded. The CLI shows CONFIRMED only
after fetching the appointment.

## Chat semantics

- Retrying a completed message replays its turn, message and trace, but refreshes the
  attached proposal's status, so the JSON can differ from the first response.
- A second request while a turn is in progress returns 409 `TURN_IN_PROGRESS`.
- Reusing a `client_message_id` with different content returns 409 `MESSAGE_ID_REUSED`.
- A failed, recoverable turn resumes from its journal under the original message ID;
  recorded tool results are never executed twice.
- At most one proposal is created per turn. A proposal attached from earlier in the
  session is labeled as previous state, and a failed proposal operation is reported
  from the recorded tool error, never as success
  (see [contract 1.2](EVALUATION_CONTRACT_V1_2.md)).
- When a newer proposal has been accepted, an older unfinished turn that tries to
  create one receives 409 `STALE_INTENT`; send a new message to change details.

## Request admission

Every request body is limited to 65,536 bytes (64 KiB). An oversized `Content-Length`
is rejected immediately, and actual received bytes are counted regardless of the
declared length, so no oversized body reaches JSON parsing. The response is 413
`REQUEST_TOO_LARGE` in the standard error envelope with a trace ID. This is a size
limit only, not rate limiting or a slow-client deadline.
