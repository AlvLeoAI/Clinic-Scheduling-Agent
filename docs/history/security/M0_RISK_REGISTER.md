# Historical security risk register — public extract

> Superseded on 2026-10-30: see README [Security history](../../../README.md#security-history).

Prepared during R1A from the private M0 risk register. This extract contains no original credential values, archive contents, patient-like records, local paths or historical object identifiers. Original evidence remains unchanged in the private workspace.

| Risk | Priority | Historical finding and current disposition |
| --- | --- | --- |
| SEC-01 | P0 | Prior discovery reported apparent vendor credentials in deleted historical ZIPs. Owner attested revocation/rotation and account usage review on 2026-10-13. This is not independent provider verification. No historical credentials were tested or migrated. |
| SEC-02 | P0 | Legacy appointment JSON had patient-like names/contact/reasons with uncertain provenance. M0 replaced the current file with an empty retired marker. Historical data is not copied into the candidate; the original history still exists privately. |
| SEC-03 | P1 | Legacy voice/orchestration and plaintext logging are excluded from the new runtime and release candidate. |
| SEC-04 | P1 | Private environment, bearer/retry state, raw outputs, audio, archives and database storage must stay excluded. Ignore rules alone do not certify safety. |
| SEC-05 | P1 | Legacy clinic/insurance catalogs have unverified provenance and are excluded. New catalog fixtures are generated independently. |

R1A is local preparation only: no Git root, commits, pushes, archive extraction, historical object copying, provider calls or database operations. The owner states the original GitHub repository is private; its visibility was not queried or changed.

Clean-root migration is the selected direction for evaluation, not erasure of historical exposure. Downstream copies/caches and the eventual repository/name/publication disposition remain separately gated. Public release remains BLOCKED. See [security/privacy](../../SECURITY_PRIVACY.md) and [M0 historical extract](../evidence/M0_report.md).
