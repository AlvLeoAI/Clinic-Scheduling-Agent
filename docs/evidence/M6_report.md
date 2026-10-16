# M6 — Reproducible demo and documentation — historical public extract

Public-safe extract prepared during R1A on 2026-10-16. Original private report and exact ledgers remain unchanged outside this candidate. Results below were recorded in the original milestone; they were not rerun from this candidate. Owner has accepted M0–M6 local technical gates. Public release remains BLOCKED by unresolved historical privacy/security and separate verification/authorization gates.

Recorded original full suite: 378 passed, 0 failed, 0 skipped, one inherited warning in 17.47 seconds. This retained 353 tests and added 25 CLI/safety/PostgreSQL cases. An isolated working-tree reproduction used a fresh private env/venv, cached pinned dependencies and a separate PostgreSQL project/port/volume; all 17 child commands exited zero, including 378 tests in 17.73 seconds. Its owned resources were removed. This was not a Git clone.

Recorded commands included full pytest with separate M6 evidence filenames, Ruff check/format, Alembic upgrade/check/current, seed twice, offline runner, concurrency demo and scripted CLI. Static docs/OpenAPI/fixture checks passed. Raw private command/output ledgers, local paths, container metadata and preservation details are withheld from this public extract. No new runtime or hosted verification occurred in R1A.

The CLI traversed chat/tools with a fake provider, displayed authoritative proposals and intercepted confirm directly. A test-only wrapper dropped the response after real commit; an independent DB read verified one appointment and one durable result before retry. Fresh client/app/engine loaded the original key, recovered a byte-identical 201 and verified the appointment. Confirmation provider requests were zero. Health passed, docs returned 200, OpenAPI had nine paths.

Two independently authenticated clients/connections raced overlapping 60/30-minute proposals. PostgreSQL raised actual 23P01; one 201, one 409 and one independently verified appointment resulted. Both same-key replays matched. The losing session received 14 independently validated alternatives; scoped cleanup removed only owned transient rows, never a global reset.

[CLI synthetic artifact](M6_cli_demo.json), [concurrency synthetic artifact](M6_concurrency_demo.json), [reconciliation](M6_M5_reconciliation.json), [offline summary](M6_offline/M5_agent_summary.md), [provenance](SYNTHETIC_PROVENANCE.md), [reproduction limits](../REPRODUCIBILITY.md), [AC matrix](../ACCEPTANCE_MATRIX.md).

Fresh local/GitHub clone, hosted Actions, live model evaluation, production/load and OS-crash certification are NOT RUN. No commit, push, history rewrite, deployment or publication occurred in M6 or R1A. Historical P0 remains unresolved; [release readiness](../RELEASE_READINESS.md) is BLOCKED.
