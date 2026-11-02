# Testing

Current status is the CI badge in the [README](README.md). Every push runs the
workflow in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) against a real
PostgreSQL 16 service with live model access disabled.

## Makefile

| Target | Does |
| --- | --- |
| `make install` | Creates `.venv` and installs the pinned lock file. |
| `make db-up` | Starts the throwaway test database (tmpfs, `127.0.0.1:15433`) and waits up to 30 s for `pg_isready`; fails if it is not ready. |
| `make test` | Full suite with real HTTP blocked. |
| `make demo` | Scripted CLI demo. |
| `make lint` | Ruff lint and format check. |
| `make ci` | Every CI step below, in order. |
| `make serve` | Migrates and seeds the **throwaway** database, then serves the API on `127.0.0.1:8000` with `AGENT_PROVIDER=demo`. |
| `make purge-chat` | Dry run of the chat retention purge. |
| `make db-down` | Stops the throwaway database; its data is discarded. |
| `make stack-up` | Builds the API and UI images and starts the [container stack](#container-stack) in demo mode. |
| `make stack-smoke` | Smoke-tests the running stack. |
| `make stack-down` | Stops the stack and discards its database. |

Two databases, two purposes:

- **Throwaway test database** (`make db-up`, port 15433): used by every Makefile
  target, including `serve`. It lives in memory and is lost on `make db-down`. The
  concurrency demo refuses a non-empty appointment table, so after booking through
  `make serve`, reset with `make db-down db-up` before `make ci`.
- **Persistent development database** (`docker compose up -d postgres`, port 15432):
  a named volume with `clinic_scheduling_dev` and `clinic_scheduling_test`; needs
  `POSTGRES_PASSWORD` in `.env`. Never point the test suite at it, because the suite
  rebuilds the schema.

Targets set every variable they need and override `.env`, so they never reach a paid
provider.

## Local database

All tests and demos use a dedicated local database. The guard in
[`app/db/safety.py`](app/db/safety.py) refuses anything other than user `clinic_demo`
on `127.0.0.1`/`localhost` with database `clinic_scheduling_test` (or
`clinic_scheduling_dev` for the server). `DATABASE_ALLOWED_HOSTS` lets migrations and
seeding reach a listed non-loopback host (the container stack uses it); tests ignore it.
See [Database targets](docs/SECURITY_PRIVACY.md#database-targets). The full suite includes a migration round
trip that rebuilds the schema, so use a disposable instance. Without `make`:

```bash
docker run -d --rm --name clinic-pg -p 127.0.0.1:15433:5432 --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=clinic_demo -e POSTGRES_PASSWORD=localdemo \
  -e POSTGRES_DB=clinic_scheduling_test postgres:16-alpine
export DATABASE_URL=postgresql+psycopg://clinic_demo:localdemo@127.0.0.1:15433/clinic_scheduling_test
export TEST_DATABASE_URL=$DATABASE_URL AGENT_PROVIDER=disabled \
  CLINIC_BOOKING_EVIDENCE_FILE=M6_booking_regression_cases.json \
  CLINIC_AGENT_EVIDENCE_FILE=M6_m4_regression_cases.json
```

Wait until `docker exec clinic-pg pg_isready -h 127.0.0.1 -U clinic_demo` succeeds
before running anything. Booking and chat tests write regression ledgers into `docs/evidence/`; the two
`CLINIC_*_EVIDENCE_FILE` variables select the gitignored ledger names. Run database
tests and demos one at a time, never concurrently.

## What CI runs

Run the same steps locally, in order:

```bash
.venv/bin/python -m scripts.check_synthetic                     # current-tree secrets and fixtures
.venv/bin/ruff check app cli scripts alembic tests evaluations ui
.venv/bin/ruff format --check app cli scripts alembic tests evaluations ui
.venv/bin/alembic upgrade head && .venv/bin/alembic check       # migrations match models
.venv/bin/pytest -q -p tests.r2a_offline_guard                  # full suite
.venv/bin/python -m evaluations.runner --evaluation-contract 1.2 --output-dir test-results/evals
.venv/bin/python scripts/demo_concurrency.py --synthetic-only --evidence test-results/concurrency.json
.venv/bin/python -m cli --synthetic-only --scripted --evidence test-results/cli.json
.venv/bin/python -m scripts.check_docs                          # links, OpenAPI parity, doc rules
```

- `-p tests.r2a_offline_guard` patches `httpx` so any real HTTP request fails the run;
  fakes, `MockTransport` and the in-process `TestClient` still work.
- The one expected warning is Starlette's deprecation of `httpx` in its `TestClient`
  (it asks for the separate `httpx2` package). Switching would add a dependency and
  change what the offline guard patches, so it is deliberately left for later.
- The evaluation runner defaults to the historical contract 1.0. Select
  `--evaluation-contract 1.2` explicitly for the current application, and always pass
  `--output-dir` so committed evidence is not overwritten.
- `check_docs` verifies local links, that `docs/openapi.json` matches the app, the
  committed offline evaluation reconciliation and the README Security history section.
  README declares exactly one `Release status: OPEN` or `Release status: BLOCKED` line;
  when BLOCKED it lists blockers as `- BLK-NN: reason`, and any current doc that
  describes a release block must cite one of those identifiers. Internal phase codes
  are not allowed in current docs.

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

## Chat retention

```bash
.venv/bin/python -m scripts.purge_chat                       # dry run: counts only
.venv/bin/python -m scripts.purge_chat --apply               # delete
.venv/bin/python -m scripts.purge_chat --retention-days 7    # override CHAT_RETENTION_DAYS
```

It uses `DATABASE_URL` and prints a JSON summary. What it deletes and keeps is described
in [security and privacy](docs/SECURITY_PRIVACY.md#chat-retention);
`tests/test_chat_retention.py` covers it.

## Running the server

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open `http://127.0.0.1:8000/docs`. Catalog, availability and booking work without any
API key. `AGENT_PROVIDER` selects the chat provider:

| Value | Chat behaviour |
| --- | --- |
| `disabled` (default) | `POST /api/v1/chat/messages` returns 501 `AGENT_PROVIDER_DISABLED` (not retryable) and stores nothing. |
| `demo` | The CLI's scripted command grammar, served with the real clock. |
| `openai` | OpenAI Responses API; requires `OPENAI_API_KEY` and `OPENAI_MODEL`. Paid. |

Chat responses carry `X-Agent-Provider: demo` or `openai`. In demo mode the grammar is
`catalog`, `availability DATE PRACTITIONER_UUID TYPE_UUID` and `propose DATE HH:MM
PRACTITIONER_UUID TYPE_UUID`; pick a weekday 2 to 90 days ahead, because the 2030
dates in the CLI examples only work with the CLI's fixed clock. `ENABLE_LIVE_OPENAI=true`
is a deprecated alias for `AGENT_PROVIDER=openai`.

`GET /api/v1/info` reports the configured provider without spending a chat turn.

## Container image

The root `Dockerfile` builds the API from `requirements-runtime.lock`, which is
`requirements-foundation.lock` without the test tools (pytest, ruff). Regenerate both
from `pyproject.toml` with `uv pip compile` (commands are in each file's header);
`tests/test_container_images.py` fails if their pins drift apart.

The image runs as uid 10001, reads configuration only from environment variables and
starts `uvicorn` on port 8000. Its `HEALTHCHECK` uses the DB-free liveness endpoint
`/api/v1/health/live`; `/api/v1/health` is readiness and also checks the database.
Migrations and seeding are one-off commands from the same image, never part of start:

```bash
docker build -t clinic-api .
docker run --rm --network host -e DATABASE_URL=… clinic-api \
  sh -c "alembic upgrade head && python -m scripts.seed"
```

Logs are one JSON line per request on stderr (uvicorn also logs to stderr). Container
log drivers, including CloudWatch's `awslogs`, capture both stdout and stderr.

## Streamlit UI

`ui/` is a separate demo client with its own lock (`ui/requirements.lock`, compiled
from `ui/requirements.in` with the command in its header) and its own image
(`docker build -t clinic-ui ui`). It reaches the API only through `API_BASE_URL`,
keeps the session bearer in server-side Streamlit state, and has no database driver.

- The provider comes from `GET /api/v1/info`; no chat turn is spent to discover it.
- In demo mode, buttons and selectors generate the three grammar commands; the slot
  list comes from `GET /api/v1/availability`, and the proposal itself from the agent.
  Free text is offered only when the provider is `openai`.
- Each proposal is a card with an expiry countdown and a separate **Confirm** button.
  Its `Idempotency-Key` is created once per proposal and kept in session state, so a
  rerun or double click resends the same key and books once.
- `SLOT_TAKEN`, `PROPOSAL_EXPIRED`, `PROPOSAL_SUPERSEDED` and
  `AGENT_PROVIDER_DISABLED` get specific messages; a retryable 503 offers a retry that
  reuses the same `client_message_id`.

HTTP logic lives in `ui/client.py` (httpx only); `tests/test_ui_client.py` covers it
with `httpx.MockTransport` in the main suite, without Streamlit. To run the page
outside containers, install the UI lock into its own venv and run
`PYTHONPATH=. API_BASE_URL=http://127.0.0.1:8000 streamlit run ui/app.py`.

## Container stack

`compose.demo.yaml` runs a disposable stack in demo mode. It is separate from
`compose.yaml` (the persistent development database on 15432) and from the throwaway
test database on 15433, so all three can coexist.

| Service | Role |
| --- | --- |
| `db` | Pinned PostgreSQL on tmpfs; no published port. |
| `migrate` | One-off `alembic upgrade head && python -m scripts.seed` from the API image, with `DATABASE_ALLOWED_HOSTS=db`. Exits when done. |
| `api` | Starts only after `migrate` succeeds; `AGENT_PROVIDER=demo`; `127.0.0.1:18000`. |
| `ui` | Starts once the API is healthy; `API_BASE_URL=http://api:8000`; `127.0.0.1:8501`. |

```bash
make stack-up      # build, start and wait for every health check
make stack-smoke   # liveness, readiness, /info, one demo catalog turn, UI health
make stack-down    # remove containers and the database
```

`scripts/smoke_stack.py` uses only the standard library, so it runs without the venv.

Earlier verification receipts per commit are kept in [project history](docs/history/).
