# Approved product architecture baseline

Public technical extract of design baseline 1.0 (2026-10-13), with the subsequently accepted M0–M6 implementation choices stated explicitly. Internal Codex execution rules, owner/workspace metadata, milestone prompts and implementation instructions are retained privately and excluded from the candidate. This document changes no HTTP, database or agent contract.

| ADR | Approved decision |
| --- | --- |
| ADR-001 | Explicit confirmation by CLI action `confirm <proposal_id>`; no LLM authorization. |
| ADR-002 | Appointment durations 30 and 60 minutes; minimum notice 24 h; maximum horizon 90 days; clinic TZ `America/Chicago`. |
| ADR-003 | Two practitioners; Monday–Friday 09:00–17:00; starts aligned every 30 minutes; weekly schedules stored in DB. |
| ADR-004 | One `PENDING` proposal per session; 10-minute TTL; immutable booking details; states `PENDING`, `CONFIRMED`, `CONFLICTED`, `EXPIRED`, `SUPERSEDED`; no slot hold. |
| ADR-005 | FastAPI `/api/v1`; 8 functional endpoints plus health; three agent tools (`get_clinic_catalog`, `check_availability`, `create_booking_proposal`). |
| ADR-006 | PostgreSQL owns conversation/session state; bounded context; session token is opaque; per-session serialization; recoverable failures. |
| ADR-007 | OpenAI Responses API, `store=false`, strict function calling, `parallel_tool_calls=false`, maximum **five** function calls per user turn, Pydantic ingress/egress. |
| ADR-008 | Independent deterministic backend testing and agent behavior evaluation; concurrency is release-critical, not just a chat demo. |

## Accepted operational precision

One fictitious clinic, two artificial practitioners, follow_up (30 minutes) and initial_consultation (60 minutes). Clinic timezone America/Chicago; weekdays 09:00–17:00; starts every 30 minutes and full intervals inside hours. Start instants satisfy inclusive elapsed UTC bounds now+24 hours through now+90*24 hours. Appointment types determine duration; callers cannot override it. An injected clock makes boundaries/DST deterministic. Availability subtracts committed appointments, and proposals hold no slot.

Proposals snapshot exact clinic/practitioner/type/start/end/duration and owning session, expire after ten elapsed minutes, allow one pending per session and never renew TTL on same-tuple reuse. Different valid details supersede pending state atomically; invalid replacements preserve it. Terminal CONFIRMED/CONFLICTED/EXPIRED/SUPERSEDED states cannot revert. Confirmation requires the owning bearer plus an explicit direct HTTP action and persistent idempotency key; no model tool can confirm.

PostgreSQL GiST exclusion prevents practitioner overlap with half-open intervals. Confirmation revalidates policy/deadlines, uses a savepoint for SQLSTATE 23P01, and atomically commits appointment, proposal state and durable result. The same key/request replays original status/body; changed request reuse conflicts. Adjacent appointments and separate practitioners can coexist. Unknown commit/response outcomes remain uncertain until same-key recovery or verified appointment retrieval. Privileged SQL is outside service policy guarantees.

## Accepted state and provider boundary

Opaque bearer lifetime is 24 hours without sliding renewal; database stores hashes. Ten relational tables hold catalog, sessions/turns/journal, proposals, appointments and idempotency. Short lease/fence transactions serialize each session; provider I/O is outside transactions. Unique source_turn_id and journaled outputs prevent repeated proposal effects.

Only catalog, availability and proposal tools are exposed. Missing/ambiguous parameters require clarification, not invented product behavior. Strict Pydantic ingress/egress, nonparallel function calls, store=false and at most five calls per user turn are retained. Manual context uses complete call/output/reasoning items, eight completed turns and a 24,000-character bound, not a token guarantee. The accepted adapter uses pinned httpx REST with injectable transport. Live model compatibility/reliability is NOT RUN.

Typed reply plans are rendered deterministically by the backend; correct visible output cannot relabel an incorrect raw decision as PASS. Completed chat replay refreshes proposal status while retaining turn/message/trace and immutable tuple; M3 confirmation replay remains byte-identical. No cancellation/rescheduling, insurance, real patients, audio, frontend, RAG, Redis or multi-agent architecture is introduced.

The authoritative implemented request/response schemas are the unchanged [OpenAPI snapshot](../openapi.json), app/schemas and route code. See [API](../API_DESIGN.md), [model](DATA_MODEL.md), [ADR index](ADR_INDEX.md), [evaluation](AGENT_EVALUATION.md) and [AC-01–12](ACCEPTANCE_MATRIX.md). No historical illustrative non-UUID request is offered as a valid API contract. R1A performs no runtime tests or publication.
