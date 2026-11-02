# System design

A synthetic, text-based scheduling backend with an LLM agent on top. The backend owns
scheduling rules, proposal state and booking; the model can only read and propose.
The architecture diagram is in the [README](README.md#architecture).

## Components

| Component | Responsibility |
| --- | --- |
| `cli/` | Demo client: private session and idempotency state, HTTP calls, verified display. `confirm <id>` goes straight to the confirm endpoint, never through chat. |
| `app/api/`, `app/schemas/` | Versioned `/api/v1` contracts, bearer-derived ownership, validated inputs, sanitized error envelopes with trace IDs. |
| `app/core/admission.py` | Rejects HTTP bodies over 64 KiB before routing or JSON parsing. |
| `app/domain/`, `app/services/scheduling.py` | Deterministic time and interval rules; availability computed from PostgreSQL. |
| `app/services/booking.py` | Immutable proposals, one-way status transitions, confirmation with revalidation, conflict mapping, durable idempotent results. |
| `app/services/chat.py`, `conversation.py`, `intent.py` | Agent loop, durable turn journal, message deduplication, per-session lease and fence, stale-intent ordering. |
| `app/agent/` | Tool registry and schemas, provider registry (`demo`, `openai`), Responses API adapter, scripted demo provider, context selection, `ReplyPlan` and template renderer. |
| `app/db/`, `alembic/` | Ten-table schema with ownership, uniqueness and exclusion constraints; synthetic catalog seed. |
| `evaluations/` | Independent interval oracle and separate raw, backend and visible graders; versioned contracts. |
| `app/services/retention.py` | Purges stored chat content of sessions expired beyond `CHAT_RETENTION_DAYS`; never touches bookings. |
| `scripts/` | Guarded demo setup and cleanup, concurrency demo, chat retention purge, current-tree secret check, doc checks. |
| `ui/` | Streamlit demo client. Reads and proposes through the API; books only through the confirm endpoint with one idempotency key per proposal. No database access. |
| `Dockerfile`, `ui/Dockerfile`, `compose.demo.yaml` | Pinned non-root API and UI images, and a one-command local stack with a one-off migrate+seed step. |

## Scheduling policy

- One synthetic clinic in `America/Chicago`, two practitioners, weekdays 09:00–17:00.
- Visit types of 30 or 60 minutes; starts on a 30-minute grid.
- At least 24 hours' notice and at most 90 days ahead (inclusive, elapsed UTC).
- Missing or ambiguous date, time, practitioner or visit type leads to a clarification;
  the backend never guesses.

## Agent loop

1. A chat request claims a short expiring lease and an increasing fence on the session,
   then releases its database transaction before calling the provider.
2. The provider, chosen by `AGENT_PROVIDER` through the registry in
   `app/agent/provider.py`, receives instructions, the selected context, three strict tool schemas
   and a strict `ReplyPlan` output schema (`store=false`, no parallel tool calls).
3. Each tool call is validated, executed and journaled with its result. After five
   calls in a turn, tool use is disabled.
4. The final `ReplyPlan` (one of `greeting`, `clarify`, `catalog`, `availability`,
   `proposal`, `confirmation_required`, `out_of_scope`) is validated and rendered from
   templates using validated tool results and fresh database reads.

Every write is fenced: a request that lost its lease cannot persist results. Context
keeps the last eight completed turns plus the current one, bounded at 24,000
characters; whole old turns are dropped, never sliced. A retried message replays its
recorded tool results instead of executing them again.

**Stale intents.** When a proposal is accepted, other unfinished turns in the session
are marked stale under the session lock. A marked turn that tries to create a proposal
gets 409 `STALE_INTENT`, so an old retry can never replace a newer choice. Turns that
predate this ordering and whose session already has proposals fail closed the same way.

## Data model

Alembic revision `0001` creates ten tables and the `btree_gist` extension. Instants are
`TIMESTAMPTZ`; sessions store only SHA-256 hashes of 256-bit random bearer tokens.

| Table | Key invariants |
| --- | --- |
| `clinics`, `practitioners`, `appointment_types`, `weekly_schedules` | Synthetic catalog; durations limited to 30/60; schedule hours checked. |
| `chat_sessions` | Token hash, fixed expiry, active turn, lease deadline, monotonic fence. |
| `chat_turns` | `UNIQUE(session_id, client_message_id)`, request fingerprint, status, stored reply. |
| `conversation_items` | Ordered JSONB items, `UNIQUE(turn_id, sequence)`, composite owner key. |
| `booking_proposals` | Immutable snapshot, TTL and status, unique source turn, one PENDING per session. |
| `appointments` | Confirmed bookings; composite FK to the exact proposal snapshot; GiST exclusion `appointments_no_overlap` on `(practitioner_id, tstzrange(starts_at, ends_at, '[)'))`. |
| `idempotency_records` | `UNIQUE(session_id, idempotency_key)`, request fingerprint, original status and body. |

## Booking and confirmation

Availability and proposals never reserve a slot. Confirmation locks the session and
proposal, checks for an existing idempotent result, revalidates policy and expiry,
inserts the appointment inside a savepoint and rechecks deadlines after any constraint
wait. An exclusion violation (SQLSTATE 23P01) rolls back the insert and records the
proposal as CONFLICTED with 409 `SLOT_TAKEN`. The appointment, the proposal status and
the idempotent result commit together. An unknown commit outcome is reported as
retryable uncertainty; retrying with the same key returns the original result.

Application services enforce business hours, grid, notice and horizon, and immutable
proposal fields. No database trigger enforces every business rule; privileged SQL is
outside the service safety boundary.

## Deployment shape

Locally, `compose.demo.yaml` runs the same images and steps a cloud deployment would
use; see [testing](TESTING.md#container-stack).

| Piece | Locally | Intended on ECS Fargate |
| --- | --- | --- |
| API | `api` service, `uvicorn` on 8000 | Service behind an ALB, arm64 (Graviton) task |
| UI | `ui` service on 8501 | Separate service behind the ALB |
| Schema and catalog | One-off `migrate` service | One-off `run-task` with the same image and a command override, before each deploy |
| Chat retention | `make purge-chat` | Scheduled task (EventBridge) running `python -m scripts.purge_chat --apply` |
| Database | tmpfs PostgreSQL, `DATABASE_ALLOWED_HOSTS=db` | RDS PostgreSQL 16 over TLS, `DATABASE_ALLOWED_HOSTS=<endpoint>` |

Two health endpoints: `/api/v1/health/live` never touches the database and is the
container health check; `/api/v1/health` is readiness and returns 503 when the
database is unreachable.

What the infrastructure step will need from this design:

- **Health checks.** ECS ignores a Dockerfile `HEALTHCHECK`, so each task definition
  needs its own (liveness for the container). Point the ALB target group at liveness
  too, or at readiness only with a generous unhealthy threshold, so a database blip
  does not cycle every task.
- **Configuration.** Environment variables only. `DATABASE_URL` and, if ever enabled,
  `OPENAI_API_KEY` come from Secrets Manager through task-definition `secrets`. The
  deployed database keeps the name `clinic_scheduling_dev` and user `clinic_demo`,
  which the guard requires; use `sslmode=verify-full&sslrootcert=<bundle path>` with
  the AWS RDS CA bundle added to the image or a mounted volume.
- **UI sessions.** Streamlit keeps session state (including the bearer token) in
  process memory over a websocket. Run one UI task, or enable ALB stickiness; the ALB
  idle timeout must allow long-lived websockets.
- **Proxy headers.** `uvicorn --proxy-headers` trusts `X-Forwarded-*` from
  `FORWARDED_ALLOW_IPS` (default `127.0.0.1`); set it to the VPC range.
- **Images.** Push the arm64 builds to ECR; CI already builds and smoke-tests them on
  native arm64 runners.
- **Exposure.** There is no identity or rate limiting (see
  [security and privacy](docs/SECURITY_PRIVACY.md#known-limitations)); a public demo
  needs at least WAF rate rules, and chat should stay on the `demo` provider.
- **Logs.** One JSON line per request on stderr; `awslogs` captures stdout and stderr.

## Key decisions

| Decision | Rationale |
| --- | --- |
| Separate explicit confirm endpoint; no confirm tool | The model can never be the reason a booking exists. |
| Typed `ReplyPlan` plus template rendering | Visible facts come from the database, so the model cannot state a booking that did not happen. |
| PostgreSQL exclusion constraint as the overlap authority | Correct under concurrency without application locks across practitioners. |
| Durable idempotency records with original body | Lost responses are recoverable without inferring success from a timeout. |
| Stateless Responses calls with a database journal | Restarts and retries resume from recorded state; no provider-side conversation dependency. |
| REST over `httpx` instead of an SDK | Injectable transport for fully offline tests. |
| One `ResponsesProvider` protocol with a registry | `demo` and `openai` share the loop; another provider (for example Anthropic) is a new registry entry that translates its API to Responses-style items. |
| Independent graders per layer | Safe backend behaviour cannot hide a wrong model decision. |
| Migrations as a one-off task, never on container start | Concurrent tasks never race on schema changes, and a failed migration blocks the deploy instead of crash-looping the service. |
| Separate liveness and readiness | Restarts only for a dead process; database outages surface as 503 readiness, not restarts. |

See [API design](docs/API_DESIGN.md), [evaluation](docs/EVALUATION.md) and
[security and privacy](docs/SECURITY_PRIVACY.md).
