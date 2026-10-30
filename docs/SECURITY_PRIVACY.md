# Security, privacy and limitations

Historical security and licensing are closed; see the README [Security history](../README.md#security-history). The preserved [M0 risk register](security/M0_RISK_REGISTER.md) is a superseded historical extract. This document describes current controls and limitations; it does not authorize deployment to untrusted clients.

Current runtime/fixtures are generated from scratch: fictitious clinic/clinicians, synthetic visit types and UUIDs, no patient name/phone/reason fields. Legacy voice code, archives and booking JSON are not runtime sources. The current-tree pattern/provenance checker does not inspect or clear history, certify provenance of old audio, or prove absence of every possible secret. Known literal fake credentials used only with MockTransport are explicitly classified; unknown pattern candidates fail. Do not upload historical blobs as evidence.

Session bearers are 256-bit random opaque values; PostgreSQL stores only hashes. API ownership uses the bearer, not caller/model-supplied IDs. Tokens are issued once, expire after 24 hours and do not slide. CLI state contains credentials and idempotency/retry data: ignored, mode 0600, backend-scoped, atomically persisted, never exported. Keep `.env` private/ignored and use fresh local database passwords. CLI/API traces never substitute for authentication.

Operational application logs omit keys, bearers, raw messages, full tool arguments and SQL exception values; they correlate route/operation/status/trace/timing and observed provider usage. Curated demo transcripts intentionally contain only artificial scheduling commands and authoritative synthetic output. Raw reasoning and request headers are not exported. Sanitized historical live token counts and estimated costs are summarized in [the evaluation report](LIVE_EVALUATION_REPORT.md); raw execution artifacts remain private and invoice totals are not independently verified.

This is not clinical software, patient identity verification, EHR integration, production authentication/security, a retention/purge system, or a compliance certification. There is no cancellation/rescheduling, holiday calendar, multi-clinic tenancy, notification, deployment hardening or production load/crash guarantee. Privileged SQL can bypass service-level policy/immutability. Session expiry does not purge persisted conversations. HTTP loopback examples and local ephemeral databases do not imply encrypted public deployment.

Live reliability claims require separately run real evaluations; scripted fake-provider counts cannot support those claims. See [release checklist](RELEASE_READINESS.md).

## Historical security disposition (closed 2026-10-30)

An earlier prototype repository, public for a period under a different name, had
committed archives containing OpenAI and ElevenLabs API keys, plus legacy demo
appointment records and audio. The keys were revoked and rotated, and the owner
reviewed provider usage for the exposure window with no unexpected activity. The
legacy repository was deleted. This repository starts from an independent clean
root (`6521b87`) built from a reviewed file allowlist; no legacy commits, archives,
audio or records were imported. gitleaks v8.30.1 reports no findings across every
ref, and every blob ever committed here is text. SEC-01 (credentials) and SEC-02
(legacy records provenance) are closed. Deletion cannot recall copies made while the
legacy repository was public; the rotated keys are no longer valid.

## Licensing (closed 2026-10-30)

Distribution is source-only under the MIT [LICENSE](../LICENSE). Third-party
dependencies are installed separately under their own licenses, inventoried in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and
[source distribution scope](SOURCE_DISTRIBUTION.md); the incorporated Alembic
template notice is included. Binary, wheelhouse or container redistribution would
need its own notice review.


## Local R3E.3 remediation boundary

The candidate adds transactional fencing of obsolete unfinished proposal mutations
and a 64 KiB HTTP body admission limit; see [API details](API_DESIGN.md).
Legacy unfinished mutations lacking ordering provenance fail closed when their
session has proposal history. Committed-output replay and uncontested recovery
remain available; no legacy backfill is performed. Conservative rejection can
require a fresh message even when an old request might have been legitimate.
Neither measure authorizes exposure to untrusted clients. F1 (anonymous appointment
capacity consumption) and F2 (aggregate provider attempts and durable state growth)
remain confirmed limitations requiring separate identity, admission and aggregate
budget decisions. F5 (dependency artifact-hash enforcement) remains a hardening gap;
version pins alone do not authenticate downloaded distribution artifacts.
No F1, F2 or F5 control is implemented by this change. Historical reports and live
model verdicts retain their original versions. No new live model reliability claim
follows from offline tests.
