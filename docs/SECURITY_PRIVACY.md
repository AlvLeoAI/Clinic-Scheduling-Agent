# Security, privacy and limitations

This document describes current controls and known limitations. The history of the
earlier credential exposure is in the README [Security history](../README.md#security-history).

## Data

All runtime data and fixtures are generated: a fictitious clinic and clinicians,
synthetic visit types and UUIDs. The schema has no patient name, phone, email, date of
birth or visit-reason fields. Sessions are anonymous.

Chat messages are stored as sent in `conversation_items` so turns can be replayed and
recovered. Session expiry stops authentication but does not delete them by itself.

## Database targets

[`app/db/safety.py`](../app/db/safety.py) checks the database URL before any connection.
It requires the `postgresql+psycopg` driver, user `clinic_demo` and database
`clinic_scheduling_test` or `clinic_scheduling_dev`.

- **Tests and demos** (which rebuild or clean the schema) accept only
  `clinic_scheduling_test` on `127.0.0.1`/`localhost` with no query string.
  `DATABASE_ALLOWED_HOSTS` has no effect on them.
- **Migrations and seeding** also accept the exact hostnames listed in
  `DATABASE_ALLOWED_HOSTS` (comma-separated, empty by default, no wildcards or ports),
  such as the compose service `db` or a managed database endpoint. The only query keys
  allowed are `sslmode` and `sslrootcert`, so a managed database can use
  `sslmode=verify-full` with its CA bundle; keys such as `host` or `options` that could
  redirect or alter the connection are refused.

`DATABASE_PASSWORD`, when set, is merged into a password-less `DATABASE_URL` before any
check, so a secret store can inject the password alone. Setting both a URL password
and `DATABASE_PASSWORD` is rejected. Neither value appears in settings errors or reprs.

## Database roles

A deployment can separate the schema owner from the runtime user.
`python -m scripts.db_roles`, run as `clinic_demo` through the same guard right after
migrations, creates or updates the role `clinic_app` with the password in
`CLINIC_APP_PASSWORD` (at least 16 characters). `clinic_app` gets `SELECT`, `INSERT`,
`UPDATE` and `DELETE` on the application tables and read-only access to
`alembic_version`; it owns nothing and cannot create, alter, drop or truncate tables.
The API and the chat purge then connect as `clinic_app`; only the one-off migration
task uses the owner. The password is sent in an `ALTER ROLE` statement, so statement
logging (`log_statement`) must stay off on that database, which is the RDS default.
Locally and in CI everything still runs as `clinic_demo`.

## Chat retention

`python -m scripts.purge_chat --apply` removes the stored chat text of every session
whose bearer expired more than `CHAT_RETENTION_DAYS` (default 30) ago and that holds
no live lease. Without `--apply` it is a dry run that only reports counts.

- **Deleted:** all `conversation_items` rows of those sessions: user messages, tool
  calls and results, encrypted reasoning, stored replies and internal markers.
- **Replaced:** each of their `chat_turns.request_hash` values becomes the sentinel
  `0000…0000` (64 zeros). The hash is a SHA-256 of the user's message, kept to detect a
  reused `client_message_id`; a short message could be recovered from it by brute
  force. The sentinel satisfies the column's hex CHECK constraint and is not the hash
  of any message.
- **Cleared:** each of their `chat_turns.assistant_message` values becomes NULL. It is
  the stored reply that a completed turn replays, and it can quote the user's request.
  Sessions purged before this column was cleared are still eligible, so the next run
  clears their replies too.
- **Kept:** the session rows; each turn's row with its id, `client_message_id`,
  status, timestamps and trace ID; proposals, appointments and idempotency records
  (whose stored confirm responses hold booking details but no chat text). Every foreign
  key stays valid and no booking is lost. Purged sessions are already past bearer
  expiry, so no chat or confirmation replay can reach the removed state.

The command locks candidate sessions with `SKIP LOCKED`, so it never races an active
chat request, and it is idempotent. The AWS sandbox runs it daily as an EventBridge
Scheduler task, connected as `clinic_app`; locally it runs only when invoked.

## AWS sandbox exposure

The sandbox (see [system design](../SYSTEM_DESIGN.md#aws-deployment)) publishes the
Streamlit UI at a `*.cloudfront.net` address. **The public UI has no authentication
and no rate limiting.** Anyone with the address gets an anonymous session and can read
availability, create proposals and book synthetic appointments, consuming demo
capacity.

That is acceptable only in the mode it is deployed in:

- The agent provider is `demo`, so no request reaches a paid model, and all data is
  synthetic.
- The stack is applied for a demo and destroyed afterwards, not left running.
- Compute is one fixed-size task per service with no autoscaling. That caps the
  Fargate charge only: CloudFront requests and data transfer beyond the free tier, load
  balancer capacity units, CloudWatch log ingestion and database storage still grow
  with traffic, and nothing rate-limits the public UI. Console budgets alert but do
  not stop spend; the real limit is that the stack is destroyed the same day.
- The API has no public route, and its Swagger UI, ReDoc and OpenAPI document are
  turned off (`API_DOCS_ENABLED=false`).

Before the sandbox runs continuously or with `AGENT_PROVIDER=openai`, the planned
control is AWS WAF on the CloudFront distribution with rate-based rules per client IP
(plus the AWS managed common rule set), followed by an identity layer. Live mode
also needs the owner's explicit go-ahead because each turn costs money.

Remaining network exposure, by design:

- Tasks have public IPv4 addresses so they can reach AWS APIs without a NAT gateway.
  No security-group rule admits inbound traffic to them from the internet.
- UI, API and one-off tasks may open HTTPS to any address. A compromised container
  could send data out over 443. Private subnets with interface endpoints would close
  this.
- Traffic inside the VPC is plain HTTP: CloudFront's VPC-origin interfaces to the
  internal ALB, the ALB to the UI, and the UI to the API, which carries the session
  bearer. The post-deploy smoke task also calls the API over HTTP with its own
  short-lived session; its security group allows only the API on 8000 and HTTPS out,
  and it holds no database credentials. TLS covers browser to CloudFront and the API to the database
  (`verify-full`, with `rds.force_ssl` on).
- The ALB accepts HTTP only from the CloudFront origin-facing managed prefix list. It
  is internal, so only CloudFront VPC origins in this VPC can reach it. Admitting
  CloudFront's service-managed VPC-origin security group instead would limit it to
  this account's distributions, but that group exists only after the first apply.
- The deploy role can be assumed only by workflow jobs in the `aws-sandbox` GitHub
  environment (main branch, required reviewer). Its trust policy matches GitHub's
  immutable OIDC subject, which includes the owner and repository IDs, so a renamed
  or re-created repository with the same name cannot assume it. It can push images, register task
  definitions (an action AWS does not scope by resource), run the migrate and smoke
  tasks, read their logs and update the two services. In effect, it can deploy any code under this stack's
  execution roles, so the reviewer approval is the control. It cannot change IAM, read
  Terraform state, reach the database or change the purge schedule. The schedule runs
  the purge family's latest revision, which the workflow registers only after a release
  has succeeded.

## Authentication and ownership

- Session bearers are 256-bit random values; PostgreSQL stores only their SHA-256 hash.
- Tokens are issued once and expire after 24 hours without sliding renewal.
- Ownership always comes from the bearer, never from IDs supplied by the caller or the
  model. Another session's resources return 404.
- The CLI keeps its bearer and idempotency keys in a gitignored file with mode 0600,
  bound to the demo backend; it refuses a state file with wrong permissions or scope.
- The Streamlit UI keeps its bearer and idempotency keys only in server-side
  `session_state`; they never reach the browser. A tab reload or a UI task restart
  discards them, so a confirmation whose outcome was uncertain can no longer be checked
  from the UI. The booking itself is safe either way (one key books at most once), but
  the user cannot learn its outcome there. The CLI's recovery path, which reloads its
  key from the 0600 file after a restart, does not transfer to the UI. Within one
  session, a newer proposal does not hide an uncertain card: it stays visible with its
  original key, and the newer proposal cannot be confirmed until it resolves.

## Logging and errors

Application logs record route, outcome code, status, trace ID, timing and provider
token usage. They omit keys, bearers, message text, full tool arguments and SQL
exception values. Error responses never echo request input; validation errors return
a generic message. Provider error bodies and request headers are discarded.

## Agent boundary

The model has three tools: catalog, availability and proposal creation. It has no
confirmation, SQL or appointment-mutation tool, and session identity never comes from
model arguments. Tool arguments and results are validated with strict Pydantic models;
the reply the user sees is rendered from templates and database reads. See
[system design](../SYSTEM_DESIGN.md#agent-loop).

## Checks

`scripts/check_synthetic.py` runs in CI and fails on unknown credential-like strings
or sensitive file types in the current tree; known fake test credentials used only
with `MockTransport` are listed explicitly. In a Git checkout it scans what `git add .`
would commit (tracked files plus untracked files that are not ignored) and the ignored
regression ledgers under `docs/evidence/`, so local build output such as Terraform
provider binaries does not fail it; without Git it walks the tree. It does not scan Git history; history was
checked separately with gitleaks (see the README). Tests block real HTTP, with two
explicit loopback-only exceptions: the `service` and `browser` tests (see
[testing](../TESTING.md)).

## Known limitations

- **Not production software.** No clinical use, patient identity verification, EHR
  integration, compliance certification, cancellation or rescheduling, holiday
  calendar, notifications or multi-clinic tenancy.
- **No identity or rate limiting.** Anyone who can reach the API can create sessions
  and proposals and consume appointment capacity; aggregate provider calls and stored
  state are not budgeted. Do not expose the API to untrusted clients without an
  identity and admission layer. The AWS sandbox exposes only the UI, under the
  conditions in [AWS sandbox exposure](#aws-sandbox-exposure).
- **Request admission is size-only.** Bodies over 64 KiB are rejected; there is no
  request-rate or slow-client control.
- **Stale-intent ordering is conservative.** Older unfinished turns that cannot prove
  their order relative to existing proposals are rejected, which can require a fresh
  message for a request that might have been legitimate.
- **Dependency pinning has gaps outside pip.** Every Python lock carries SHA-256
  hashes and is installed with `--require-hashes`, and base images are pinned by
  digest. The Chromium binary used by the optional browser tests is pinned only by the
  Playwright version that downloads it.
- **Privileged SQL bypasses service rules.** Policy and immutability are enforced in
  services and constraints, not by triggers on every field.
- **Demo deployments only.** Loopback examples, local databases and the container
  stack do not imply an encrypted or hardened deployment. The local stack's database
  password is a fixed demo value (override with `DEMO_DB_PASSWORD`); its database
  publishes no port. The AWS sandbox is a short-lived demo, not production hosting.
- **The UI is a demo client.** It has no login: whoever reaches it gets an anonymous
  session. It keeps the bearer token in server-side Streamlit state, hides error
  tracebacks and disables usage statistics.
- **Live model evidence is smoke-level.** See [evaluation](EVALUATION.md). The
  offline raw-layer counts (15 PASS, 9 FAIL, 1 NOT RUN) come from scripted fixtures
  whose nine failures are deliberate negative controls; they are separate from the
  live smoke runs and are not model reliability evidence.

## Licensing

Distribution is source-only under the MIT [LICENSE](../LICENSE). Dependencies are
installed separately under their own licenses, listed in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md), which also carries the notice for
the incorporated Alembic migration template. Redistributing binaries, wheels or
containers would need its own notice review.
