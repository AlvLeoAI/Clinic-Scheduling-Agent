# Security, privacy and limitations

**Public release is BLOCKED pending explicit historical-risk decisions and separate publication authorization.** The R3D.1 audit was accepted as a deliverable; that does not constitute owner risk acceptance. M0 owner revocation/rotation and usage-review attestation is preserved, not independently verified by provider calls. No history rewrite, force-push, publication, Notion update or deployment is authorized. See the preserved [M0 risk register](security/M0_RISK_REGISTER.md) and later [current status](CURRENT_STATUS.md).

Current runtime/fixtures are generated from scratch: fictitious clinic/clinicians, synthetic visit types and UUIDs, no patient name/phone/reason fields. Legacy voice code, archives and booking JSON are not runtime sources. The current-tree pattern/provenance checker does not inspect or clear history, certify provenance of old audio, or prove absence of every possible secret. Known literal fake credentials used only with MockTransport are explicitly classified; unknown pattern candidates fail. Do not upload historical blobs as evidence.

Session bearers are 256-bit random opaque values; PostgreSQL stores only hashes. API ownership uses the bearer, not caller/model-supplied IDs. Tokens are issued once, expire after 24 hours and do not slide. CLI state contains credentials and idempotency/retry data: ignored, mode 0600, backend-scoped, atomically persisted, never exported. Keep `.env` private/ignored and use fresh local database passwords. CLI/API traces never substitute for authentication.

Operational application logs omit keys, bearers, raw messages, full tool arguments and SQL exception values; they correlate route/operation/status/trace/timing and observed provider usage. Curated demo transcripts intentionally contain only artificial scheduling commands and authoritative synthetic output. Raw reasoning and request headers are not exported. Sanitized historical live token counts and estimated costs are summarized in [the evaluation report](LIVE_EVALUATION_REPORT.md); raw execution artifacts remain private and invoice totals are not independently verified.

This is not clinical software, patient identity verification, EHR integration, production authentication/security, a retention/purge system, or a compliance certification. There is no cancellation/rescheduling, holiday calendar, multi-clinic tenancy, notification, deployment hardening or production load/crash guarantee. Privileged SQL can bypass service-level policy/immutability. Session expiry does not purge persisted conversations. HTTP loopback examples and local ephemeral databases do not imply encrypted public deployment.

Any public release requires owner resolution of historical risk, scope/claim review and separate authorization. Live reliability claims additionally require separately authorized real evaluations; scripted fake-provider counts cannot support those claims. See [release checklist](RELEASE_READINESS.md).

The legacy repository was private and archived at the historical cutover. Final
R3B checks returned HTTP 404; the owner subsequently confirmed intentional removal.
No current archive/visibility claim can be re-attested for that inaccessible
repository. Deletion does not prove elimination of old exposure or third-party copies.
Revocation/rotation remains an owner attestation, separate from clean-root checks.

During R3D.1 the owner stated that the legacy appointment records and audio were
entirely synthetic demo material. This is a provenance attestation; excluded audio
and historical records were not extracted or independently authenticated. The owner
also stated that the outcome of the earlier provider usage review was not recorded
or uncertain. No finding of either misuse or absence of misuse follows from that
uncertainty. The exact reviewed clean commit has no known dependency on those legacy
materials; this narrow technical finding does not close historical exposure.

The proposed disposition for historical credentials, provenance and retained copies
is **MITIGATED / OWNER ACCEPTANCE REQUIRED**. All owner acceptance fields remain
**UNDECIDED** in the separate private decision package. Retain private evidence and
reopen the relevant finding if specific contrary provenance, accessible sensitive
copies or unresolved abuse becomes known. No proof of eliminating every unknown
third-party copy is claimed or required.

Licensing is a separate gate. The retained MIT license covers the project's grant;
third-party dependencies retain their own licenses. The audited pinned runtime has
32 distributions with license metadata/files, including LGPL and MPL components.
This is bounded inventory evidence, not a certification of all redistribution
formats. Owner confirmation of included-source rights and required notices remains
UNDECIDED. The proposed release is reviewed source only; bundled runtimes, native
libraries, images, historical audio and private evidence require separate review.


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
or public-release authorization follows from offline tests.
