# Final acceptance matrix — AC-01 through AC-12

These rows describe the original owner-accepted M0–M6 local evidence, not newly executed candidate tests. R1A is static preparation only; candidate runtime, Git root, fresh clone and hosted CI are NOT RUN. Milestone evidence is local and synthetic. Status is limited to the stated proof; public release remains BLOCKED. M6 results are recorded in [actual execution report](evidence/M6_report.md).

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
| AC-09 | Tool/result grounding | PASS (offline) | Independent oracle and corrupt-observation controls reject invented results; raw errors remain separate. Live semantic quality NOT RUN. |
| AC-10 | Sanitized correlated traces | PASS | Retained key/message log checks, CLI transcript bearer checks and M6 artifact/current-tree checks. |
| AC-11 | Public repository security/privacy addressed | BLOCKED | Owner rotation attested; historical credential/audio/privacy issue remains P0. |
| AC-12 | Reproducible offline demo | PASS (local) | Fresh venv/private env/separate PostgreSQL working-tree reproduction: 378 tests, CLI and real concurrency PASS; fresh clone remains NOT RUN. |

PASS requires actual execution and does not waive AC-11. Hosted CI, real-model evaluations, fresh clone and publication are separate unexecuted gates, not implicit successes.
