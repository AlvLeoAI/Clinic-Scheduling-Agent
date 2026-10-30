# Clinic Scheduling Agent

[![CI](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/workflows/ci.yml)

An LLM scheduling agent for a synthetic clinic where the model can read the calendar
and propose a slot, but only deterministic code and PostgreSQL can book it.

## Why this exists

Booking an appointment is a write with real consequences: a double-booked clinician,
a slot the patient never agreed to, or a "you're booked" message when nothing was
saved. A language model is good at understanding a request and choosing what to look
up; it cannot guarantee any of those outcomes. This project keeps the model on the
side of the line where it is strong (interpreting the request and calling read-only
or proposal tools) and puts every booking guarantee in FastAPI services and database
constraints. A booking happens only through a separate, idempotent confirmation call
that the model has no tool for.

## Architecture

```mermaid
flowchart LR
    U[Client / CLI] -->|chat message| API[FastAPI /api/v1]
    API --> LOOP[Agent loop<br/>max 5 tool calls per turn]
    LOOP <-->|tool calls + typed ReplyPlan| LLM[LLM provider]
    LOOP --> T1[get_clinic_catalog]
    LOOP --> T2[check_availability]
    LOOP --> T3[create_booking_proposal]
    LOOP --> R[Template renderer<br/>facts read from DB]
    R -->|assistant text| U
    U -->|POST /proposals/id/confirm<br/>Idempotency-Key| C[Confirm endpoint]
    T1 & T2 & T3 --> PG[(PostgreSQL)]
    C --> PG
    PG --- X[EXCLUDE no-overlap<br/>UNIQUE idempotency key]
```

The model chooses tools and returns a typed `ReplyPlan` (for example `availability` or
`clarify`). It never writes the text the user sees. Proposals are immutable, expire
after ten minutes and do not hold the slot. See [system design](SYSTEM_DESIGN.md).

## Demo

<!-- GIF: docs/demo.gif (to be recorded) -->

Live demo: coming soon. Until then, the scripted CLI demo in the quickstart below runs
the full flow against a local database.

## Three guarantees

| Guarantee | Enforced in | Verified by |
| --- | --- | --- |
| The model cannot confirm a booking | [`app/agent/tools.py`](app/agent/tools.py) registers three tools, none of which confirms; [`app/api/booking.py`](app/api/booking.py) `confirm_proposal` is the only path to an appointment | `tests/test_agent_protocol.py::test_tool_definitions_are_strict_required_and_allowlisted`, `::test_malformed_and_unapproved_tools_rejected`; `tests/test_chat.py::test_immediate_booking_injection_after_valid_proposal_never_confirms` |
| User-visible text comes only from templates | [`app/agent/replies.py`](app/agent/replies.py) renders each `ReplyPlan` kind from validated tool results and fresh database reads | `tests/test_chat.py::test_fabricated_model_booking_or_id_cannot_be_returned`; `tests/test_reply_quality.py::test_renderer_refreshes_postgres_when_availability_changes` |
| Overlaps and idempotency are enforced by PostgreSQL | [`app/db/models.py`](app/db/models.py) GiST exclusion `appointments_no_overlap` and `UNIQUE(session_id, idempotency_key)`; [`app/services/booking.py`](app/services/booking.py) maps SQLSTATE 23P01 to 409 `SLOT_TAKEN` | `tests/test_constraints.py::test_overlap_rejected`, `::test_idempotency_key_scoped_to_session`; `tests/test_booking.py::test_coordinated_overlap_exclusion_race`, `::test_key_reused_for_different_proposal_cannot_overwrite_result` |

CI also runs a two-connection race (`scripts/demo_concurrency.py`) and a demo that
drops the HTTP response after a committed confirmation, then recovers the original
result with the same idempotency key.

## Evaluation

Every case is graded on three independent layers: the **raw model decision** (tool
choice, arguments, reply plan), **backend state** (what PostgreSQL actually contains)
and the **visible reply**. A safe rendered reply never earns credit for a wrong model
decision. The offline suite has 25 scripted cases, including deliberate wrong
decisions that the graders must catch.

Live results are smoke-level validation only. Eight runs against the `gpt-6-luna`
alias (reasoning effort `none`) between 2026-10-21 and 2026-10-26 covered five
scenarios: catalog lookup, natural-language availability, proposal creation, an
ambiguous request and an attempted conversational confirmation. Two first runs
failed the raw-model layer (a time-format schema mismatch, and wrong metadata on a
refusal); the backend layer passed in all eight runs and no appointment was created.
After narrow fixes, retests passed all layers. These are single samples, not a
reliability estimate, and raw run manifests are not published. Details:
[evaluation](docs/EVALUATION.md).

## Quickstart

Requires Python 3.12 and Docker. No API key is needed.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-foundation.lock
docker run -d --rm --name clinic-pg -p 127.0.0.1:15433:5432 \
  -e POSTGRES_USER=clinic_demo -e POSTGRES_PASSWORD=localdemo \
  -e POSTGRES_DB=clinic_scheduling_test postgres:16-alpine
export DATABASE_URL=postgresql+psycopg://clinic_demo:localdemo@127.0.0.1:15433/clinic_scheduling_test
export TEST_DATABASE_URL=$DATABASE_URL ENABLE_LIVE_OPENAI=false \
  CLINIC_BOOKING_EVIDENCE_FILE=M6_booking_regression_cases.json \
  CLINIC_AGENT_EVIDENCE_FILE=M6_m4_regression_cases.json
.venv/bin/pytest -q -p tests.r2a_offline_guard        # full suite, real HTTP blocked
.venv/bin/python -m cli --synthetic-only --scripted   # migrates, seeds, runs the demo
docker stop clinic-pg
```

The CLI uses a scripted provider with a fixed command grammar (`catalog`,
`availability ...`, `propose ...`, `confirm <id>`) and a fixed clock of 2030-01-07; it
shows the tool flow and backend enforcement, not natural-language quality. Without an
OpenAI key the HTTP chat endpoint returns 503. More in [testing](TESTING.md).

## Security history

This repository starts from a clean root commit (`6521b87`, 2026-10-16). An earlier
prototype repository, public for a period under a different name, had committed archives
containing OpenAI and ElevenLabs API keys, along with demo appointment records and audio
from a retired voice version.

What was done:

- The exposed OpenAI and ElevenLabs keys were revoked and rotated.
- The project was rebuilt from a reviewed file allowlist. No legacy commits, archives,
  audio or appointment records were carried over, and the legacy repository was deleted.
- gitleaks v8.30.1 reports no findings across every ref of this repository. Every blob
  ever committed here is text: no audio, archives or credential files.
- CI runs a current-tree secret and synthetic-fixture check on every push.

What remains: nothing in this repository. Provider usage for the exposure window was
reviewed with no unexpected activity.

Release status: OPEN

## Documentation

- [System design](SYSTEM_DESIGN.md): components, data model, key decisions.
- [API design](docs/API_DESIGN.md): routes, errors, idempotency and recovery.
- [Evaluation](docs/EVALUATION.md): graders, contracts, live smoke results.
- [Testing](TESTING.md): running the suite, CI and local setup.
- [Security and privacy](docs/SECURITY_PRIVACY.md): controls, limitations, licensing.
- [Project history](docs/history/): phase records, milestone evidence, superseded reports.

All data is synthetic: fictitious clinicians, UUID identifiers and fixed 2030 dates.
MIT licensed; dependencies keep their own licenses ([notices](THIRD_PARTY_NOTICES.md)).
