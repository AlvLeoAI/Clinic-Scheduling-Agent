# Clinic Scheduling Agent

A synthetic text scheduling prototype built with FastAPI, PostgreSQL and validated agent tools. The backend owns scheduling rules, proposal state and atomic booking; a model cannot confirm an appointment.

**Local demonstration only. Historical Git credentials/audio/privacy remains a P0 release blocker. Publication, deployment and live OpenAI evaluation are not authorized. No production, regulatory or real-clinic claims are made.**

## What is demonstrated

- Chicago weekday scheduling, 30/60-minute visits, a 30-minute start grid, 24-hour notice and 90-day horizon.
- Immutable ten-minute booking proposals and an explicit `confirm <proposal_id>` action.
- PostgreSQL exclusion constraints, durable idempotency and recovery after a committed response is lost.
- Persistent, fenced chat orchestration using only catalog, availability and proposal tools.
- Independent backend tests, scripted agent evaluations and grader negative controls.

The offline CLI uses a deterministic fake provider with an explicit command grammar. It demonstrates validated tool flow and backend enforcement, not natural-language model reliability. Live OpenAI evaluations are **NOT RUN**. M5's raw scripted decisions remain 15 PASS / 9 intentional FAIL / 1 NOT RUN; backend and visible enforcement passed all 25 fixture cases.

## Local setup and demos

Use Python 3.12 and the pinned `requirements-foundation.lock`; follow [local setup](docs/OPERATIONS.md). No OpenAI or ElevenLabs key is needed. The active server is `app.main:app`.

```bash
# After private environment, local PostgreSQL and pinned dependencies are prepared:
.venv/bin/python scripts/demo_concurrency.py --synthetic-only
.venv/bin/python -m cli --synthetic-only --scripted
.venv/bin/python -m cli --synthetic-only
```

Demos use only the guarded local `clinic_scheduling_test` database and an injected clock of 2030-01-07 15:00 UTC. The scripted demos clean only their own rows after verifying results. The interactive CLI retains its synthetic session in ignored mode-0600 `.local/cli_state.json`. Do not run DB demos/tests concurrently. The concurrency script refuses a nonempty appointment table and never resets it.

```text
catalog
availability 2030-01-09 00000000-0000-4000-8000-000000000101 00000000-0000-4000-8000-000000000201
propose 2030-01-09 09:00 00000000-0000-4000-8000-000000000101 00000000-0000-4000-8000-000000000201
confirm <proposal_id_returned_by_backend>
```

Confirmation bypasses the provider. A timeout is UNCERTAIN; retry the same command and private state to preserve its key. The CLI displays CONFIRMED only after retrieving the actual appointment.

## Evidence and documentation

- [Architecture](SYSTEM_DESIGN.md), [ADR index](docs/ADR_INDEX.md), [data integrity](docs/DATA_MODEL.md).
- [API/OpenAPI](docs/API_DESIGN.md), [operations and recovery](docs/OPERATIONS.md).
- [Agent/evaluation boundaries](docs/AGENT_EVALUATION.md), [M5 reconciliation](docs/M5_RECONCILIATION.md).
- [Tests and CI](TESTING.md), [security/privacy](docs/SECURITY_PRIVACY.md).
- [Acceptance matrix](docs/ACCEPTANCE_MATRIX.md), [release checklist](docs/RELEASE_READINESS.md).
- [M6 actual execution report](docs/evidence/M6_report.md), [accepted M5 evidence](docs/evidence/M5_report.md).

This is an R1A local release candidate prepared without a Git root. Its files received static content/publication review; runtime verification from this candidate, Git initialization, fresh-clone testing, hosted CI and publication are NOT RUN. Historical M0–M6 results do not substitute for those gates. The original repository remains private and unchanged; its visibility was not queried during R1A.

## Provenance and release boundary

Legacy voice code, audio dependencies, clinic/insurance fixtures, historical appointment records, Git objects and private development state are excluded from this candidate. The original workspace and its accepted private evidence remain preserved separately. The only data/appointments.json file here is an empty retired marker required by retained static checks; it is not a runtime seed.

The MIT license is retained. Product contracts are unchanged; see the [approved product baseline](docs/ARCHITECTURE_BASELINE.md) and [synthetic evidence provenance](docs/evidence/SYNTHETIC_PROVENANCE.md). Public milestone reports are labeled extracts of historical results, not new executions. Raw ledgers, internal execution prompts and local paths are withheld.

Before any future setup, obtain R1B authorization and use an isolated verification copy, unique Compose project, fresh loopback port/password and new volume. Never reuse the original development or test databases. A local review is not public release approval.
