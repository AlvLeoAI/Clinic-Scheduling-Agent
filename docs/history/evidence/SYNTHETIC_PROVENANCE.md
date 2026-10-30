# Synthetic evidence provenance

> Superseded on 2026-10-30: see README [Security history](../../../README.md#security-history).

Prepared during R1A (2026-10-16) by static review of preserved M0–M6 source and artifacts. This is provenance/content review, not a new evaluator or database run. No vendor API, GitHub API or original database was used.

The dataset has 25 cases, version 1.0.0, with explicitly Synthetic-prefixed inputs and independently generated fixed catalog UUIDs. FixtureProvider always attaches httpx.MockTransport, uses model label synthetic-offline-m5, and exposes no live-client branch. Its exporter emits request fingerprints, not bearer headers. Snapshots select only synthetic proposal/appointment fields.

The candidate preserves these accepted JSON artifacts byte-for-byte after complete structural review. Renderer, combined grader/oracle, dataset and per-request prompt fingerprints match the recorded metadata. No credential, contact, patient-name, visit-reason or request-header fields were found in the exported case documents.

| Artifact | SHA-256 | Provenance |
| --- | --- | --- |
| [M5_agent_cases.json](../../evidence/M5_agent_cases.json) | 6d0a7cb696ce3e547ad469cd2cc27d150237e938e6d83081bd77dd0d6b8c5cec | 25 artificial MockTransport cases; actual usage null; live NOT RUN. |
| [M6_offline/M5_agent_cases.json](M6_offline/M5_agent_cases.json) | eab45157d15ea0880421777cb30cfba090419e715b64e9fce0c9fdbe80be5101 | 25 artificial MockTransport cases; actual usage null; live NOT RUN. |

The M6 CLI/concurrency JSON contains generated synthetic catalog/proposal/appointment/session/trace identifiers and frozen 2030 dates. UUIDs and observed backend PIDs are not authentication credentials. The CLI artifact records response loss after commit and verified same-key recovery; the concurrency artifact records separate connections, actual 23P01 and an independent final-state read before owned cleanup. They contain no bearer or private state. Summary Markdown and M6 reconciliation refer only to those artificial runs.

Raw decisions remain 15 PASS / 9 intentional FAIL / 1 NOT RUN; backend/visible 25 PASS each. The single NOT RUN is the absent raw decision in a critical injected provider error; backend 503/zero-appointment safety actually ran. These fixture counts measure the declared scripted dispositions, not live model reliability.

Public milestone reports are labeled extracts. Exact private preservation/publication manifests and raw command ledgers remain outside this candidate. Original evidence was not edited. Historical Git privacy/security, owner release acceptance, new-root verification, fresh clone and hosted CI remain separately gated.
