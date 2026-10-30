# Security, privacy and limitations

This document describes current controls and known limitations. The history of the
earlier credential exposure is in the README [Security history](../README.md#security-history).

## Data

All runtime data and fixtures are generated: a fictitious clinic and clinicians,
synthetic visit types and UUIDs. The schema has no patient name, phone, email, date of
birth or visit-reason fields. Sessions are anonymous.

Chat messages are stored as sent in `conversation_items` so turns can be replayed and
recovered. Session expiry stops authentication but does not delete stored
conversations; there is no retention or purge job.

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
- **Local only.** Loopback examples and local databases do not imply an encrypted or
  hardened deployment.
- **Live model evidence is smoke-level.** See [evaluation](EVALUATION.md); offline
  counts are not model reliability evidence.

## Licensing

Distribution is source-only under the MIT [LICENSE](../LICENSE). Dependencies are
installed separately under their own licenses, listed in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md), which also carries the notice for
the incorporated Alembic migration template. Redistributing binaries, wheels or
containers would need its own notice review.
