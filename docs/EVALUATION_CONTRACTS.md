# Versioned evaluation contracts

Select **1.0** or **1.1** for their frozen historical contracts, or **1.2** for current proposal-grounding verification. See the exact [v1.2 specification](EVALUATION_CONTRACT_V1_2.md).
Both runner APIs accept `evaluation_contract="1.2"` and both CLIs accept
`--evaluation-contract 1.2`. The default remains 1.0; there is no content-based
fallback or automatic version upgrade. Unknown versions fail before case/database
effects. Each report records its contract, scorer version, ordered source list and
SHA-256 fingerprint. Dataset, application prompt, tool-schema and scorer versions
are separate identities.

The original `graders.py`, `live_graders.py` and independent `oracle.py` are frozen.
Original S1–S5 live verdicts and private reports are never regraded or overwritten.
Legacy grader tests keep their original fixtures and imports. Tests of the current
application use explicit 1.2; the mocked R2 integration test also asserts 1.0's
specific S2 incompatibility. These are different contracts, not expected-failure
markers hiding an application error.

## Contract 1.1

`graders_v1_1.py` and `live_graders_v1_1.py` delegate the unchanged raw/backend
predicates to v1, adding independent cross-field reply validation and successful
availability result metadata checks. Non-clarification plans require empty
missing_fields, even when a case omits an exact list expectation. Missing or
malformed evidence fails closed; absent model output stays NOT RUN.

For nonempty availability, the complete sentence must match the finite grammar:
the existing interval prefix, an ordered list of Chicago-local timestamp pairs,
the existing refresh/non-reservation disclaimer, and exactly:

> Select one of the returned intervals to request a booking proposal. Final booking requires separate explicit confirmation.

All pairs must equal a complete independent oracle result for the same session's
successful availability tool call. Returned practitioner/type/date/timezone/duration
and intervals must match the arguments and oracle. Missing, extra, reordered,
fabricated or mixed intervals and extra prose fail. No permissive substring or
blanket acceptance is used. After that exact check, a private evidence copy is
projected to v1 wording so all existing owner/status/ID/time/booking checks can be
reused; original observations remain unchanged. Old nonempty wording intentionally
fails 1.1 because it lacks the approved guidance. Empty availability and the other
finite response forms retain their existing contracts.

Proposal prose requires an authoritative owned projection, and confirmed projections
require an actual appointment with explicit non-agent confirmation provenance or
an authorized initial appointment. Unsupported booking-success prose remains
forbidden. Rendering cannot make an invalid raw plan pass; the three layer verdicts
remain independent. M5 fixture PASS can include an intentional raw FAIL, whereas
R2 smoke PASS requires all three layers PASS. Mocked success is not model quality.

## Offline verification

Use a new isolated synthetic PostgreSQL cluster/runtime and private output paths.
Do not reuse or reset development/R2 databases. The R2 endpoint guard still requires
127.0.0.1:15433 inside the verified runtime; a private network namespace can supply
that endpoint without reassigning the host's existing R2 port.

```bash
.venv/bin/pytest -q -p tests.r2a_offline_guard
.venv/bin/python -m evaluations.runner --evaluation-contract 1.2 --output-dir test-results/contract-1.2
.venv/bin/python -m evaluations.live_runner --dry-run --evaluation-contract 1.2 --output-dir .local/contract-1.2
```

Use separate output directories for explicit 1.0 compatibility runs. The current
application's new wording is expected to fail the old availability grammar;
report that result independently of 1.1 correctness. CI now explicitly selects 1.2
for current application evaluations. Raw snapshots and operational evidence stay private. The source tree contains only reviewed aggregate live summaries and component hashes, never raw private execution records or credentials.

R2C.2 S2 and S5 each completed one separately authorized live regression with all three layers PASS; see [preserved results](LIVE_EVALUATION_REPORT.md). Any further paid retest needs fresh source/prompt/
schema/dataset/contract fingerprints, explicit scenario selection and owner opt-in,
reviewed provider compatibility/pricing and existing request/token/cost limits.
No paid request or live experiment is authorized by this contract document.

## Contract 1.2 and historical compatibility

The v1.0/v1.1 grader modules and fixtures remain byte-for-byte preserved. The shared
version dispatcher now offers 1.2. Because 1.1's composite fingerprint includes that
dispatcher, a newly calculated composite hash changes even though its grader modules
are unchanged; original execution manifests retain the original hashes. New reports
record all source dependencies, contract-document and independent control hashes.

The new finite grammar distinguishes current results, previous recoverable state,
validated failures and absence. A raw proposal plan after a failed call still fails
raw evaluation. Safe rendering can pass backend/visible layers independently. The
observer records turn and client-message identities for exact call/output correlation;
these are private evidence fields, not new public API fields. No historical live
execution is regraded. Complete current verification and compatibility results are
reported separately in [testing](../TESTING.md).

The fingerprinted contract specifications and historical live report retain their
original preparation-time wording. Later commit/CI status is recorded in
[current status](CURRENT_STATUS.md), without changing those bytes or retrospectively
rescoring a live execution. Contract 1.2 passed offline hosted checks at `e1b572f`;
it has no live GPT-6 Luna evaluation evidence.
