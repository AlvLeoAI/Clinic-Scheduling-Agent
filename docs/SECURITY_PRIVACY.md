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

## Chat retention

`python -m scripts.purge_chat --apply` removes stored chat content of every session
whose bearer expired more than `CHAT_RETENTION_DAYS` (default 30) ago and that holds
no live lease. Without `--apply` it is a dry run that only reports counts.

- **Deleted:** all `conversation_items` rows of those sessions: user messages, tool
  calls and results, encrypted reasoning, stored replies and internal markers.
- **Replaced:** each of their `chat_turns.request_hash` values becomes the sentinel
  `0000…0000` (64 zeros). The hash is a SHA-256 of the user's message, kept to detect a
  reused `client_message_id`; a short message could be recovered from it by brute
  force. The sentinel satisfies the column's hex CHECK constraint and is not the hash
  of any message.
- **Kept:** sessions, turns, proposals, appointments and idempotency records, so every
  foreign key stays valid and no booking is lost. Purged sessions are already past
  bearer expiry, so no chat or confirmation replay can reach the removed state.

The command locks candidate sessions with `SKIP LOCKED`, so it never races an active
chat request, and it is idempotent. It is not scheduled yet; a daily cron job, a
Railway cron service or an EventBridge rule running a scheduled container task with
`python -m scripts.purge_chat --apply` would each be enough.

## Authentication and ownership

- Session bearers are 256-bit random values; PostgreSQL stores only their SHA-256 hash.
- Tokens are issued once and expire after 24 hours without sliding renewal.
- Ownership always comes from the bearer, never from IDs supplied by the caller or the
  model. Another session's resources return 404.
- The CLI keeps its bearer and idempotency keys in a gitignored file with mode 0600,
  bound to the demo backend; it refuses a state file with wrong permissions or scope.

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
with `MockTransport` are listed explicitly. It does not scan Git history; history was
checked separately with gitleaks (see the README). Tests block all real HTTP.

## Known limitations

- **Not production software.** No clinical use, patient identity verification, EHR
  integration, compliance certification, cancellation or rescheduling, holiday
  calendar, notifications or multi-clinic tenancy.
- **No identity or rate limiting.** Anyone who can reach the API can create sessions
  and proposals and consume appointment capacity; aggregate provider calls and stored
  state are not budgeted. Do not expose the API to untrusted clients without an
  identity and admission layer.
- **Request admission is size-only.** Bodies over 64 KiB are rejected; there is no
  request-rate or slow-client control.
- **Stale-intent ordering is conservative.** Older unfinished turns that cannot prove
  their order relative to existing proposals are rejected, which can require a fresh
  message for a request that might have been legitimate.
- **Dependencies are version-pinned, not hash-pinned.** Pins alone do not authenticate
  downloaded artifacts.
- **Privileged SQL bypasses service rules.** Policy and immutability are enforced in
  services and constraints, not by triggers on every field.
- **Local only.** Loopback examples, local databases and the container stack do not
  imply an encrypted or hardened deployment. The stack's database password is a fixed
  demo value (override with `DEMO_DB_PASSWORD`); its database publishes no port.
- **The UI is a demo client.** It has no login: whoever reaches it gets an anonymous
  session. It keeps the bearer token in server-side Streamlit state, hides error
  tracebacks and disables usage statistics.
- **Live model evidence is smoke-level.** See [evaluation](EVALUATION.md); offline
  counts are not model reliability evidence.

## Licensing

Distribution is source-only under the MIT [LICENSE](../LICENSE). Dependencies are
installed separately under their own licenses, listed in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md), which also carries the notice for
the incorporated Alembic migration template. Redistributing binaries, wheels or
containers would need its own notice review.
