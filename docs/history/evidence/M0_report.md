# M0 — Security and migration baseline — historical public extract

> Superseded on 2026-10-30: see README [Security history](../../../README.md#security-history).

Public-safe extract prepared during R1A on 2026-10-16. Original private report and exact ledgers remain unchanged outside this candidate. Results below were recorded in the original milestone; they were not rerun from this candidate. Owner has accepted M0–M6 local technical gates. Public release remains BLOCKED by unresolved historical privacy/security and separate verification/authorization gates.

M0 recorded 11 static checks PASS, 0 FAIL, including 63 positive and 18 negative ignore cases. It preserved the owner handoff, added environment/secret/output exclusions, replaced uncertain appointment data with an empty retired marker, and specified a new artificial catalog. No runtime, database or provider test was run in M0.

Owner attested vendor credential revocation/rotation and usage review; no credential validity check was performed. Historical archives, credentials, audio and patient-like records were neither imported nor cleared. See [risk register](../security/M0_RISK_REGISTER.md) and [seed provenance](../security/M0_SYNTHETIC_SEED_SPEC.md).
