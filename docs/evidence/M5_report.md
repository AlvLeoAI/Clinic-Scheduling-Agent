# M5 — Offline evaluation and independent grading — historical public extract

Public-safe extract prepared during R1A on 2026-10-16. Original private report and exact ledgers remain unchanged outside this candidate. Results below were recorded in the original milestone; they were not rerun from this candidate. Owner has accepted M0–M6 local technical gates. Public release remains BLOCKED by unresolved historical privacy/security and separate verification/authorization gates.

Recorded full suite: 353 passed, 0 failed, 0 skipped, one inherited warning. The independent backend category had 234 passes. M5 added 25 offline scenarios, 24 grader/unit cases (including 16 corrupt-observation controls) and 11 wire/error/timeout cases. The standalone 25-case fixture gate passed.

Raw scripted decisions remain 15 PASS / 9 intentionally injected FAIL / 1 NOT RUN; backend and visible safety each 25 PASS. Critical case 19 injected provider HTTP 500, observed safe 503 and zero appointments; no raw decision existed to grade. The whole safety scenario ran. All nine deliberately bad decisions failed their intended graders; backend correction did not convert them to raw PASS.

Cases exercise typed-plan correction separation, refreshed four-state proposal replay without new effects, and the unchanged REST adapter through MockTransport. No M4 application change was made. Actual model reliability, compatibility, costs/latency and live evaluations are NOT RUN. [Accepted synthetic cases](M5_agent_cases.json), [provenance](SYNTHETIC_PROVENANCE.md), [reconciliation](../M5_RECONCILIATION.md).
