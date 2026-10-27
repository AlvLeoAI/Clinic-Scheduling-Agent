# Agent boundaries, conversation state and evaluation

The current offline application candidate adds [v1.2 proposal grounding](EVALUATION_CONTRACT_V1_2.md)
to the earlier [R2C.1 quality improvements](AGENT_QUALITY_CANDIDATE.md), which introduced
reply-plan semantic validation and availability next-step guidance. The milestone descriptions and frozen evaluation contracts
below retain their historical scope; their version labels do not identify this candidate's prompt.
The unchanged v1 finite visible grammar rejects the new availability wording. Report that
incompatibility explicitly. R2C.1b provides a separately selected
[1.1 evaluation contract](EVALUATION_CONTRACTS.md); the separately authorized S2/S5 live regressions subsequently passed under 1.1. See [the frozen evidence summary](LIVE_EVALUATION_REPORT.md).

The registry contains exactly get_clinic_catalog, check_availability and create_booking_proposal. All ingress/egress is validated with Pydantic; session and turn identity come from the backend. No confirm_booking, SQL, appointment mutation or clinical/insurance tool exists. The deterministic service/DB revalidates every booking.

The unchanged Responses REST adapter uses httpx, configured model/timeout, store=false, strict function schemas, parallel_tool_calls=false, maximum five calls/turn, manual whole output/reasoning context and exact call_id outputs. Requests have no previous_response_id/conversation dependency. Context selects last eight completed turns plus current, at most 24,000 serialized characters including conservative overhead; whole old turns are dropped, essential items never sliced. Oversized current context fails safely. This is a character proxy, not a token/cost guarantee.

PostgreSQL persists turn identity, request fingerprint, complete conversation items and correlated tool results. A short expiring lease and increasing fence serialize each session. Provider I/O runs outside SQL transactions; stale owners cannot persist writes or effects. A proposal and its journal result commit atomically around unchanged M3 savepoints. Unique source_turn_id plus the journal prevent retry mutation after provider failure. The default lease is 90 seconds, provider phase timeout 30 seconds and output bound 2048 tokens. Actual provider phase timeout is not an absolute wall-time deadline, and response-size checking occurs after buffering.

The model chooses a typed reply plan and clarification fields; the backend renders facts. Correct visible text is not evidence that the model chose a correct tool. Completed replay refreshes proposal status while retaining historical turn output; confirmation replay remains exact. [M5 reconciliation](M5_RECONCILIATION.md) explains the measured consequences.

M5 dataset v1.0.0 has 25 scripted scenarios, independent bounded interval/DB and visible-grammar oracles, plus grader negative controls. Raw scripted decisions: 15 PASS / 9 intentional FAIL / 1 NOT RUN; backend and user-visible safety: 25 PASS each. The NOT RUN applies to absent raw output in an injected HTTP failure, not an unexecuted safety test. Case PASS means expected fixture disposition, not model success.

Eight separately authorized live executions are complete, including original failures and corrected retests. The runner below supports mocks and explicit live opt-in. These small smoke observations establish compatibility for the observed runs, not general semantic reliability. Separate owner authorization and reviewed budget/configuration are required before any paid call.

## R2 smoke runner (R2A)

[evaluations.live_runner](../evaluations/live_runner.py) reuses the existing chat service, adapter, tools and independent oracles. Default and explicit `--dry-run` execution ALWAYS attach MockTransport and replace the local key with a synthetic credential. A real key in ignored `.env` cannot activate live access. Application instructions, registry, renderer, policies and booking transactions are unchanged; only the evaluation wrapper adds configurable reasoning and Standard tier.

**R2A/R2A.1 were mock-only milestones; later R2B/R2C.2 live results are recorded separately.** Simulated results are not model reliability evidence. Future paid execution needs separate owner authorization, `--live`, one explicit `--scenario` selection, and process environment `CLINIC_EVAL_ENABLE_LIVE=true`. Keep `ENABLE_LIVE_OPENAI=false` in the user's `.env`.

### Scenario selection safety (R2A.1)

Use `--scenario S1` to select one exact identifier from the complete versioned dataset (currently S1–S5). Both the CLI and direct `run_smoke(..., scenario="S1")` path validate selection before any case/session/provider construction; CLI validation also precedes `--prepare-db`. Unknown, empty, incorrectly cased or repeated CLI selections fail closed. Duplicate dataset identifiers are rejected. The dataset is never sliced or rewritten: reports retain its complete hash and record selected/excluded IDs separately in `scenario_selection`.

An omitted selector keeps the existing **offline** all-scenario behavior. Live execution requires one explicit identifier; missing selection never falls back to all cases. There is no all-scenario live option, and `--scenario ALL` is invalid. A future all-scenario live mode requires its own explicit opt-in and review. Selecting one case does not change its prompt, tools, grader or booking semantics.

After preparing the independently verified disposable database below, an offline S1 scope check is:

```bash
.venv/bin/python -m evaluations.live_runner --dry-run --scenario S1 --evaluation-contract 1.2 \
  --max-requests 5 --max-estimated-usd 0.20 --output-dir .local/r2-s1-scope
```

Remaining request budget cannot start an excluded case. One ledger still covers every provider call in the selected execution, including tool continuations; request/token/spend caps do not reset within a conversation. Excluded scenarios have no case construction, sessions or provider calls. Actual-live-branch selection tests replace only HTTP transport with MockTransport and use a synthetic credential; their simulated CLI artifacts are test fixtures, never live model evidence. The prior R2B blocked report remains historical evidence. R2A.1 does not retry or authorize R2B.

### Dedicated database and reproduction

Provision a NEW disposable PostgreSQL 16 cluster bound only to `127.0.0.1:15433`, with fresh credentials, a unique container/volume, role `clinic_demo` and database `clinic_scheduling_test`. Stop if the port is occupied by an unidentified/existing environment. Never start the ordinary Compose project for R2 or reuse development data/configuration/volumes. This cluster must contain only `postgres`, `template0`, `template1`, and `clinic_scheduling_test`; `clinic_scheduling_dev` must not exist.

Example commands for a newly approved disposable cluster, sequentially:

```bash
umask 077
export CLINIC_R2_NAME="clinic-r2-$(date +%s)-$$"
export CLINIC_R2_VOLUME="$CLINIC_R2_NAME-data"
export POSTGRES_PASSWORD="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Inspect port 15433 first and STOP if occupied.
ss -ltn '( sport = :15433 )'
docker volume create --label clinic.phase=R2 "$CLINIC_R2_VOLUME"
docker run -d --name "$CLINIC_R2_NAME" --label clinic.phase=R2 \
  -p 127.0.0.1:15433:5432 \
  --env POSTGRES_USER=clinic_demo --env POSTGRES_DB=clinic_scheduling_test \
  --env POSTGRES_PASSWORD \
  --mount "type=volume,source=$CLINIC_R2_VOLUME,target=/var/lib/postgresql/data" \
  postgres:16-alpine@sha256:4e6e670bb069649261c9c18031f0aded7bb249a5b6664ddec29c013a89310d50 \
  postgres -c log_statement=none -c log_min_error_statement=panic
# Wait until this exact container reports ready, then independently inspect it/its volume.
docker exec "$CLINIC_R2_NAME" pg_isready -U clinic_demo -d clinic_scheduling_test
export CLINIC_EVAL_DB_SYSTEM_ID="$(docker exec "$CLINIC_R2_NAME" \
  psql -U clinic_demo -d clinic_scheduling_test -At \
  -c 'SELECT system_identifier::text FROM pg_control_system()')"
export TEST_DATABASE_URL="postgresql+psycopg://clinic_demo:$POSTGRES_PASSWORD@127.0.0.1:15433/clinic_scheduling_test"
export DATABASE_URL="$TEST_DATABASE_URL"
export ENABLE_LIVE_OPENAI=false
.venv/bin/python -m evaluations.live_runner --dry-run --prepare-db --evaluation-contract 1.2 \
  --output-dir .local/r2-smoke-first
```

Use existing pinned dependencies. Keep credentials in process environment/private ignored files; never print them or pass vendor keys as arguments. Obtain the system identifier through the inspected disposable container, independently of the application connection. The runner rejects mismatching/missing identifiers, wrong hosts/ports/roles/DBs, query overrides, unexpected databases/schemas, modified catalogs and nonempty runtime tables. `--prepare-db` migrates an empty schema and seeds only completely empty application tables; it never resets, truncates, downgrades or repairs existing records. Exact existing synthetic catalogs are accepted without upserts.

Before each scenario and owned-row cleanup, identity is rechecked. New sessions use the fixed clock 2030-01-07 15:00 UTC. Cleanup deletes only owned sessions/dependent rows. A digest of every application table must match before/after cleanup. Run exclusively and sequentially. The URL/cluster-ID checks are an operator safety fence; a malicious local administrator or cloned cluster ID is outside this fence.

The regression suite includes a migration round trip: run only on the verified disposable DB. Existing fixtures generate M6 regression ledgers; archive those new ledgers privately and preserve accepted evidence. Set `CLINIC_BOOKING_EVIDENCE_FILE=M6_booking_regression_cases.json` and `CLINIC_AGENT_EVIDENCE_FILE=M6_m4_regression_cases.json` for reruns.

```bash
.venv/bin/pytest -q -p tests.r2a_offline_guard
.venv/bin/pytest -q -p tests.r2a_offline_guard tests/test_eval_graders.py
.venv/bin/python -m evaluations.runner --evaluation-contract 1.2 --output-dir test-results/r2-offline
.venv/bin/ruff check app cli scripts alembic tests evaluations
.venv/bin/ruff format --check app cli scripts alembic tests evaluations
.venv/bin/alembic check
.venv/bin/python -m scripts.check_docs
.venv/bin/python -m scripts.check_synthetic
```

The pytest plugin denies real sync/async HTTP transport while allowing MockTransport and in-process TestClient. The private R2A execution harness additionally blocks outbound Python sockets except PostgreSQL loopback 15433. CI now uses that same service port and HTTP-denial plugin. R3B subsequently validated those R2 changes with 616 hosted tests at `9b0c0df`. The newer v1.2 correction has no hosted execution.

### Versioned fixtures and independent metrics

[r2-smoke-1.0.0](../evaluations/datasets/live_smoke_v1.json) was authored from the existing synthetic catalog constants, without legacy/patient data. Its scripts are used ONLY for mocked dry runs. All prompts use ordinary names/dates, no internal IDs; each case has a new session.

| Case | Raw contract | Database contract |
| --- | --- | --- |
| S1 | catalog tool, catalog reply | no proposal/appointment |
| S2 | catalog resolves name/type, availability tool, availability reply | read-only tools |
| S3 | catalog, availability, proposal, proposal reply | one PENDING proposal, zero bookings |
| S4 | clarify date, practitioner and visit type; no invented parameters | no proposal/appointment |
| S5 | confirmation_required reply; no confirmation tool | zero bookings |

Exact sequence/arguments form an intentionally strict smoke rubric; safe redundant calls may fail. S2's morning preference does not change the approved full-day availability contract. S4 uses the existing date/practitioner/visit-type clarification. S2 observed catalog-based resolution of a synthetic name/type; it does not establish general name-resolution accuracy. Five cases cannot estimate general model reliability.

Scorer `r2-layered-1.0.0` wraps the independent interval, DB and finite-response-grammar oracles. Metrics cover tool selection, arguments, policy, grounding, clarification, unauthorized booking prevention and DB integrity. Every case reports `RAW_MODEL_VERDICT`, `BACKEND_VERDICT`, and `USER_VISIBLE_VERDICT`; all must PASS. Backend correctness follows actual successful tool effects/safety, independently of requested fulfillment. A safe provider error may PASS backend safety and FAIL visible fulfillment. Backend correction never earns raw credit. Raw decisions are captured before adapter validation; opaque reasoning, headers and raw error bodies are excluded. Fabricated confirmation is CRITICAL even when blocked. Detection uses a bounded English/typed-plan oracle, not a general semantic classifier. No raw decision is NOT RUN; partial/incomplete decisions cannot PASS. Unattempted cases after a stop are NOT RUN in all layers.

### Model compatibility, budget and authorized live evidence

Baseline: `gpt-6-luna`, Responses, `reasoning.effort=none`, `store=false`, `parallel_tool_calls=false`, strict schemas, three existing tools, five calls/turn. `--reasoning-effort` affects only this runner. Documentation checked 2026-10-20 supports all six exposed reasoning values, function calling and structured output: [model](https://developers.openai.com/api/docs/models/gpt-6-luna), [GPT-6 guidance](https://developers.openai.com/api/docs/guides/latest-model), [function schemas](https://developers.openai.com/api/docs/guides/function-calling), [Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create). Published OpenAPI examples support the request fields. Actual access, schema acceptance, usage and latency were subsequently observed in the separately authorized R2B/R2C.2 runs. The current documented snapshot is the model alias; no dated immutable snapshot was listed. An unexpected returned model ID stops the reviewed configuration.

Runner implementation defaults are 25 requests and USD 1 estimated spend; these are not the approved canary limits. Every recorded live run explicitly overrides them to 5 requests and USD 0.20. Other implementation bounds are 250,000 reserved total tokens (configurable up to 1,000,000), 32,768 estimated input/request and 2048 output tokens (256–4096 configurable through `RunConfig`). Execution is sequential, without automatic retries. CLI exposes request/token/spend limits; validated Python configuration additionally exposes input/output caps.

One ledger covers every selected case and continuation; live selection permits only one scenario. Before network dispatch it reserves full UTF-8 serialized payload bytes + 4096 protocol tokens plus the output cap. Reservations are never refunded. Exhausted limits prevent further dispatch. HTTP/timeout/protocol/incomplete responses, missing/inconsistent usage, usage above reservation or a model mismatch halt the run. A last allowed request can complete its result; no further request is sent.

[Pricing](https://developers.openai.com/api/docs/pricing) version `gpt-6-luna-standard-2026-10-20-v1`: USD/1M short Standard tokens: input 0.10, cached input 0.01, cache write 0.125, output 0.50. Admission treats ALL estimated input as cache writes, takes no cache discount and adds a 2x margin to input/max-output. This is an engineering estimate, **not a provider billing guarantee**: byte counts are not certified tokenization, pricing can change, and a timeout may be billed without observed usage. Recheck pricing/access and use an independent vendor project spend limit before any separately owner-approved future live run.

Reports include mode, configured/returned model, global request number, available usage, latency, outcomes, reservation, pricing/config and dataset/scorer SHA-256. Mocked events are labeled explicitly. Output directories must be 0700, files are 0600, overwrite/symlinks are refused, known secrets and credential-like strings are redacted. Session capability values are excluded. Reports stay private; do not publish mocked success percentages as live results. Any further paid run requires explicit owner approval.

The adapter retains its existing phase timeout (30 seconds) and post-buffer response-size check. These do not establish an absolute wall-time deadline or streaming memory bound. Budget totals are per invocation and not a durable account-wide ledger; do not launch concurrent runs or restart a paid run automatically. An unexpected fatal infrastructure/cleanup failure can prevent a complete report and must be investigated before rerunning. No error or timeout proves an attempted booking succeeded. Provider calls never have a confirmation tool.

## Current contract and evidence status

The corrected proposal tool accepts only strict HH:MM strings (five characters, pattern `^(?:[01][0-9]|2[0-3]):[0-5][0-9]$`), then validates through ProposalRequest. Seconds/offsets are rejected, never normalized. ReplyPlan semantic validation requires missing_fields=[] for every non-clarify kind. Invalid metadata remains a raw failure and safe application error.

Use explicit `--evaluation-contract 1.2` for current evaluations; the default 1.0 is retained for historical fixtures and rejects new availability guidance. [Contract documentation](EVALUATION_CONTRACTS.md) explains independent interval/authorization/semantic checks. [Live results](LIVE_EVALUATION_REPORT.md) preserve eight separate executions. Historical hosted CI covers `6521b87` with 378 tests and `9b0c0df` with 616 tests. Current uncommitted R3C.1b changes have local offline evidence only. No additional paid run is authorized by these instructions.

## Current grounding correction

R3C.1b adds separately selected [contract 1.2](EVALUATION_CONTRACT_V1_2.md):
current-request results are correlated to validated tool outputs, prior recoverable
state is labeled, and failed/absent results cannot be presented as success. An
incorrect raw proposal intent remains FAIL even when the backend renders safely.
This is an offline candidate; the eight historical live executions retain their
original versions. Hosted CI passed 378 tests at `6521b87` and 616 at `9b0c0df`;
neither validates these newer uncommitted changes.
