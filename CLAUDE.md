# Clinic Scheduling Agent

FastAPI + PostgreSQL scheduling backend with an LLM agent (OpenAI Responses API over
httpx). The model may only read and propose; booking happens only through
`POST /api/v1/proposals/{id}/confirm`. Keep it that way: never add a confirm tool or
let model text reach the user (replies are rendered from templates in
`app/agent/replies.py`).

## Verify (throwaway database, never a dev DB)

Shortest path: `make db-up ci db-down` (throwaway tmpfs database on 15433, every CI
step in order). `make serve` also uses that throwaway database; compose.yaml is the
separate persistent dev database on 15432 and must never be used for tests.

The DB guard (`app/db/safety.py`) only accepts user `clinic_demo` on loopback with
database `clinic_scheduling_test`/`clinic_scheduling_dev`. The suite rebuilds the
schema, so use a disposable tmpfs container at the CI-pinned digest on
`127.0.0.1:15433`, and remove it afterwards:

```bash
docker run -d --rm --name <unique-name> -p 127.0.0.1:15433:5432 --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=clinic_demo -e POSTGRES_PASSWORD=<random> -e POSTGRES_DB=clinic_scheduling_test \
  postgres:16-alpine@sha256:4e6e670bb069649261c9c18031f0aded7bb249a5b6664ddec29c013a89310d50
export DATABASE_URL=postgresql+psycopg://clinic_demo:<random>@127.0.0.1:15433/clinic_scheduling_test
export TEST_DATABASE_URL=$DATABASE_URL AGENT_PROVIDER=disabled OPENAI_API_KEY= OPENAI_MODEL= \
  CLINIC_BOOKING_EVIDENCE_FILE=M6_booking_regression_cases.json \
  CLINIC_AGENT_EVIDENCE_FILE=M6_m4_regression_cases.json
```

Then run the CI steps in order (see `TESTING.md` / `.github/workflows/ci.yml`):
check_synthetic, ruff check + format, alembic upgrade + check, pytest with
`-p tests.r2a_offline_guard`, evaluations runner with `--evaluation-contract 1.2
--output-dir test-results/...`, concurrency demo, scripted CLI, check_docs. Run DB
steps sequentially. Always set the two `CLINIC_*_EVIDENCE_FILE` vars: tests write
ledgers into `docs/evidence/`.

## Rules that are easy to break

- Chat retention: `python -m scripts.purge_chat` (dry run) or `--apply`. It may only
  delete `conversation_items` and blank `chat_turns.request_hash` to the all-zero
  sentinel; never delete sessions, turns, proposals, appointments or idempotency rows.
- `AGENT_PROVIDER` is `disabled` (default), `demo` or `openai`; `ENABLE_LIVE_OPENAI` is a
  deprecated alias for `openai`. Never select `openai` or run live evals without the
  owner's explicit go-ahead per run: they cost money. New providers go in the
  `PROVIDERS` registry in `app/agent/provider.py` behind `ResponsesProvider`; `app/`
  must not import from `cli/`.
- Do not edit `docs/EVALUATION_CONTRACT_V1_2.md` or `tests/test_graders_v1_2.py`: they
  are hash-pinned by `evaluations/scoring.py` and `tests/test_evaluation_versions.py`.
- `evaluations.runner` defaults to contract 1.0 and to writing into `docs/evidence/`;
  always pass `--evaluation-contract 1.2` and `--output-dir`.
- `docs/evidence/M5_agent_cases.json` is reconciled by `scripts/check_docs.py`; don't
  move it. `README.md`, `SYSTEM_DESIGN.md`, `TESTING.md` are copied by name in
  `scripts/reproduce_local.py`.
- Current docs are only: README, SYSTEM_DESIGN, TESTING, THIRD_PARTY_NOTICES,
  docs/API_DESIGN, docs/EVALUATION, docs/SECURITY_PRIVACY. Phase records live in
  `docs/history/`; it is frozen (link-path fixes only) and never gates CI.
- `check_docs.py` enforces: exactly one `Release status: OPEN|BLOCKED` line in README;
  blocks described anywhere current must cite a `- BLK-NN: reason` listed in README;
  no phase codes (R1A, M5, S3...), "owner acceptance" or "UNDECIDED" in current docs.
  Use `BLK-NN` as a placeholder in examples.
- No hardcoded test counts or commit hashes in current docs; the README CI badge is
  the status.
- Don't alter the README "Security history" section without the owner.
- Commit and push only when asked; work on a branch; the owner merges PRs.
