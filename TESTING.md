# Testing

Current status is the CI badge in the [README](README.md). Every push runs the
workflow in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) against a real
PostgreSQL 16 service with live model access disabled.

## Local database

All tests and demos use a dedicated local database. The guard in
[`app/db/safety.py`](app/db/safety.py) refuses anything other than user `clinic_demo`
on `127.0.0.1`/`localhost` with database `clinic_scheduling_test` (or
`clinic_scheduling_dev` for the server). The full suite includes a migration round
trip that rebuilds the schema, so use a disposable instance:

```bash
docker run -d --rm --name clinic-pg -p 127.0.0.1:15433:5432 \
  -e POSTGRES_USER=clinic_demo -e POSTGRES_PASSWORD=localdemo \
  -e POSTGRES_DB=clinic_scheduling_test postgres:16-alpine
export DATABASE_URL=postgresql+psycopg://clinic_demo:localdemo@127.0.0.1:15433/clinic_scheduling_test
export TEST_DATABASE_URL=$DATABASE_URL ENABLE_LIVE_OPENAI=false \
  CLINIC_BOOKING_EVIDENCE_FILE=M6_booking_regression_cases.json \
  CLINIC_AGENT_EVIDENCE_FILE=M6_m4_regression_cases.json
```

Booking and chat tests write regression ledgers into `docs/evidence/`; the two
`CLINIC_*_EVIDENCE_FILE` variables select the gitignored ledger names. Run database
tests and demos one at a time, never concurrently.

## What CI runs

Run the same steps locally, in order:

```bash
.venv/bin/python -m scripts.check_synthetic                     # current-tree secrets and fixtures
.venv/bin/ruff check app cli scripts alembic tests evaluations
.venv/bin/ruff format --check app cli scripts alembic tests evaluations
.venv/bin/alembic upgrade head && .venv/bin/alembic check       # migrations match models
.venv/bin/pytest -q -p tests.r2a_offline_guard                  # full suite
.venv/bin/python -m evaluations.runner --evaluation-contract 1.2 --output-dir test-results/evals
.venv/bin/python scripts/demo_concurrency.py --synthetic-only --evidence test-results/concurrency.json
.venv/bin/python -m cli --synthetic-only --scripted --evidence test-results/cli.json
.venv/bin/python -m scripts.check_docs                          # links, OpenAPI parity, doc rules
```

- `-p tests.r2a_offline_guard` patches `httpx` so any real HTTP request fails the run;
  fakes, `MockTransport` and the in-process `TestClient` still work.
- The evaluation runner defaults to the historical contract 1.0. Select
  `--evaluation-contract 1.2` explicitly for the current application, and always pass
  `--output-dir` so committed evidence is not overwritten.
- `check_docs` verifies local links, that `docs/openapi.json` matches the app, the
  committed offline evaluation reconciliation, the README Security history section,
  and that current docs contain no release-gate or internal phase wording.

## Test markers

| Marker | Meaning |
| --- | --- |
| `unit` | Deterministic checks without PostgreSQL or a provider. |
| `postgres` | Requires the local test database. |
| `api` | HTTP contracts through the in-process client. |
| `agent_offline` | Scripted or mocked provider, protocol and grader checks. |
| `agent_live` | Reserved for opt-in live runs; excluded by default in `pyproject.toml`. |

## Demos

- **Concurrency** (`scripts/demo_concurrency.py`): two sessions with separate
  connection pools request overlapping 60- and 30-minute slots for one practitioner. A
  synchronization point makes PostgreSQL resolve a real race: one 201, one 409
  `SLOT_TAKEN` from the exclusion constraint, verified through a third connection. It
  refuses to run if the appointment table is not empty and deletes only its own rows.
- **Scripted CLI** (`python -m cli --synthetic-only --scripted`): runs catalog,
  availability and proposal through chat, then drops the HTTP response after a
  committed confirmation, restarts the app and recovers the original result with the
  same idempotency key.
- **Interactive CLI** (`python -m cli --synthetic-only`): grammar `catalog`;
  `availability DATE PRACTITIONER_UUID TYPE_UUID`; `propose DATE HH:MM PRACTITIONER_UUID
  TYPE_UUID`; `confirm PROPOSAL_UUID`; `quit`. State is kept in the gitignored
  `.local/cli_state.json` (mode 0600). After an uncertain confirmation, repeat the same
  `confirm` with the same state to reuse its idempotency key.

## Running the server

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open `http://127.0.0.1:8000/docs`. Catalog, availability and booking work without any
API key. With `ENABLE_LIVE_OPENAI=false` (the default), `POST /api/v1/chat/messages`
returns 503 because no provider is configured; the CLI supplies its own scripted
provider.

Earlier verification receipts per commit are kept in [project history](docs/history/).
