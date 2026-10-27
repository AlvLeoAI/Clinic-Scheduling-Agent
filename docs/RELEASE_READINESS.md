# Release-readiness checklist

**Public release: BLOCKED (P0).** Repository remains PRIVATE; Current R3C.1b authorization is limited to local offline remediation. No publication, deployment, Git commit/push or additional paid evaluation is authorized.

| Check | Status | Evidence boundary / next action |
| --- | --- | --- |
| Historical Git credential/audio/privacy exposure | BLOCKED / P0 | Explicit owner disposition and audit remain required; a clean root cannot erase old objects, clones or caches |
| R1A preservation and reviewed export | PASS | Accepted private manifests and source preservation |
| R1B independent root | PASS | Root `6521b87`, no historical ancestry; historical verification |
| R1C private hosted CI | PASS | 378 tests at `6521b87`, PostgreSQL, 24 original controls, offline evaluations and demos |
| R1B local / R1C remote fresh clone | PASS | Approved root only, independent storage/runtime/test database |
| R1D private cutover | PASS | Clean canonical repository; legacy private and archived at cutover; later HTTP 404 plus owner-confirmed removal; retained identity/ref/remote receipts |
| Fresh remote visibility verification during R2D | NOT RUN | No remote settings/API operations; preserve private state |
| Current R2 local regression | PASS | Accepted 616-test R2C.1b run, historical and v1.1 negative controls |
| R3B hosted CI / fresh-clone reproduction | PASS | 616 tests at `9b0c0df`; historical commit-scoped evidence |
| R3C.1b local regression | PASS | 682 tests under v1.2; original four reproduction failures corrected; no new live evidence |
| Current R3C.1b hosted CI | NOT RUN | Uncommitted v1.2 grounding correction is outside both hosted baselines |
| R2B live evidence completeness | PASS | Six executions across five cases; original S3 FAIL/PASS/FAIL and S5 FAIL/PASS/PASS remain frozen |
| R2C.2 S2 / S5 observed regressions | PASS | Separate contract 1.1 runs, each PASS/PASS/PASS; no reliability estimate |
| R2D documentation and evidence freeze | PASS (local review) | Sanitized summaries and private hashes; accepted historical freeze |
| PERF-001 / repeated-sample latency evidence | BLOCKED / NOT RUN | S4 took 22.597177 seconds; no statistical characterization or approved SLO |
| Redistribution and final publication approval | BLOCKED | Owner content/security/licensing disposition and explicit authorization required |
| Production, clinical or regulatory certification | NOT RUN | Outside this synthetic prototype's scope |

Maturity: synthetic local demonstration prototype. Typed rendering, bounded fixture grammar, character-based context accounting, per-phase timeout, buffered response checks and session-expiry recovery remain limitations. There is no retention/purge policy or production load/OS-crash certification. PASS is limited to its stated proof and never waives the P0 blocker.

Original reports stay private and unchanged. Public-facing summaries contain no raw transcripts, operational identifiers or private evidence links. See [evaluation limitations](LIVE_EVALUATION_REPORT.md), [acceptance matrix](ACCEPTANCE_MATRIX.md), [security](SECURITY_PRIVACY.md) and [reproducibility](REPRODUCIBILITY.md).
