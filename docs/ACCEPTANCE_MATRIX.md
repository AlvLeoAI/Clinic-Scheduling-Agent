# Final acceptance matrix — AC-01 through AC-12

These rows retain accepted M0–M6 safety evidence with later R1/R2 scope identified separately. No application suite was rerun in R2D. Historical hosted CI covers 378 tests at root `6521b87`; the latest accepted local R2C.1b suite has 616 passing tests. Public release remains BLOCKED. See [live evidence](LIVE_EVALUATION_REPORT.md) and [release scope](RELEASE_READINESS.md).

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
| AC-11 | Public repository security/privacy addressed | BLOCKED | Owner rotation attested; historical credential/audio/privacy issue remains P0. |
| AC-12 | Reproducible offline demo | PASS (local) | Fresh venv/private env/separate PostgreSQL working-tree reproduction: 378 tests, CLI and real concurrency PASS; R1B/R1C fresh clones subsequently passed for the approved root; current uncommitted R2 clone proof is NOT RUN. |

PASS requires actual execution and does not waive AC-11. Root-commit hosted CI/fresh clones and eight live smoke executions are recorded separately; no statistical reliability or current R2 hosted-validation claim follows. Publication is BLOCKED.
