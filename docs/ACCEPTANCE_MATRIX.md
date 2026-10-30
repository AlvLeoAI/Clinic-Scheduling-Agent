# Final acceptance matrix — AC-01 through AC-12

These rows retain accepted M0–M6 safety evidence with later verification attributed separately. No application suite was rerun in R2D or this R3D.2 documentation phase. Hosted CI covers 378 tests at root `6521b87`, 616 at `9b0c0df` and 682 at committed `e1b572f` under explicit v1.2. These are offline checks; no live v1.2 model run occurred. Historical security and licensing are closed; see the README [Security history](../README.md#security-history). See [current status](CURRENT_STATUS.md), [live evidence](LIVE_EVALUATION_REPORT.md) and [release scope](RELEASE_READINESS.md).

| ID | Requirement | Status | Proof / boundary |
| --- | --- | --- | --- |
| AC-01 | No booking without explicit confirm | PASS | M3/M4/M5 unauthorized-tool/false-confirmation controls; M6 direct-confirm route/provider-counter proof. |
| AC-02 | Non-overlap per practitioner | PASS | Real GiST constraints, retained coordinated races and M6 separate-client/PID 60-/30-minute race. |
| AC-03 | Approved temporal policies | PASS | Retained unit/API/confirmation revalidation: Chicago/DST, hours/weekdays/grid/durations, inclusive 24h/90d. |
| AC-04 | Immutable proposal, one pending, TTL/supersede | PASS | Retained lifecycle/snapshot tests and four-state replay; M6 terminal client projection. |
| AC-05 | Idempotent confirmation | PASS | Sequential/concurrent key tests, retained changed-payload rejection and M6 stable private key across restart. |
| AC-06 | Committed response-loss recovery | PASS | Real commit then injected HTTP loss, independent DB read and exact same-key recovery; no timeout inference. |
| AC-07 | Session isolation/persistence | PASS | M4/M5 concurrent sessions, restart context and ownership; private CLI state. |
| AC-08 | Strict bounded tools, no confirm tool | PASS | Three-tool schema/argument/output, five-call and fencing tests; no M6 agent-boundary change. |
| AC-09 | Tool/result grounding | PASS (offline) | Independent oracle and corrupt-observation controls reject invented results; raw errors remain separate. Separately versioned live samples are recorded; original S3 and S5 raw failures remain frozen. |
| AC-10 | Sanitized correlated traces | PASS | Retained key/message log checks, CLI transcript bearer checks and M6 artifact/current-tree checks. |
| AC-11 | Public repository security/privacy addressed | PASS | Closed 2026-10-30: keys revoked and rotated, provider usage reviewed with no unexpected activity, gitleaks v8.30.1 clean across all refs, no legacy records/audio/archives in any committed blob; source-only MIT licensing. See [security](SECURITY_PRIVACY.md). |
| AC-12 | Reproducible offline demo | PASS (commit-scoped) | M6 working-tree reproduction passed 378 tests; R1B/R1C fresh clones passed for the root; R3B local/remote clones passed 616 at `9b0c0df`; R3C.2 local/remote clones passed 682 at `e1b572f`, including concurrency and recovery demos. |

PASS requires actual execution. Hosted CI/fresh clones and eight historical live smoke executions are separate evidence. They do not establish statistical reliability, live v1.2 correctness or hosted validation of later documentation-only commits.
