# Security, privacy and limitations

**Public release is BLOCKED by unresolved historical Git credentials/audio/privacy (P0).** M0 owner revocation/rotation and usage-review attestation is preserved, not independently verified by provider calls. No history rewrite, force-push, publication, Notion update or deployment is authorized. See the preserved [M0 risk register](security/M0_RISK_REGISTER.md).

Current runtime/fixtures are generated from scratch: fictitious clinic/clinicians, synthetic visit types and UUIDs, no patient name/phone/reason fields. Legacy voice code, archives and booking JSON are not runtime sources. The current-tree pattern/provenance checker does not inspect or clear history, certify provenance of old audio, or prove absence of every possible secret. Known literal fake credentials used only with MockTransport are explicitly classified; unknown pattern candidates fail. Do not upload historical blobs as evidence.

Session bearers are 256-bit random opaque values; PostgreSQL stores only hashes. API ownership uses the bearer, not caller/model-supplied IDs. Tokens are issued once, expire after 24 hours and do not slide. CLI state contains credentials and idempotency/retry data: ignored, mode 0600, backend-scoped, atomically persisted, never exported. Keep `.env` private/ignored and use fresh local database passwords. CLI/API traces never substitute for authentication.

Operational application logs omit keys, bearers, raw messages, full tool arguments and SQL exception values; they correlate route/operation/status/trace/timing and observed provider usage. Curated demo transcripts intentionally contain only artificial scheduling commands and authoritative synthetic output. Raw reasoning and request headers are not exported. Sanitized historical live token counts and estimated costs are summarized in [the evaluation report](LIVE_EVALUATION_REPORT.md); raw execution artifacts remain private and invoice totals are not independently verified.

This is not clinical software, patient identity verification, EHR integration, production authentication/security, a retention/purge system, or a compliance certification. There is no cancellation/rescheduling, holiday calendar, multi-clinic tenancy, notification, deployment hardening or production load/crash guarantee. Privileged SQL can bypass service-level policy/immutability. Session expiry does not purge persisted conversations. HTTP loopback examples and local ephemeral databases do not imply encrypted public deployment.

Any public release requires owner resolution of historical risk, scope/claim review and separate authorization. Live reliability claims additionally require separately authorized real evaluations; scripted fake-provider counts cannot support those claims. See [release checklist](RELEASE_READINESS.md).

The legacy repository was private and archived at the historical cutover. Final
R3B checks returned HTTP 404; the owner subsequently confirmed intentional removal.
No current archive/visibility claim can be re-attested for that inaccessible
repository. Deletion does not prove elimination of old exposure, third-party copies,
audio or patient-like fixture provenance risks. Revocation/rotation remains an owner
attestation, separate from current clean-root checks. P0 is still unresolved.
