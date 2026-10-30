# Current verification and decision status

Recorded 2026-10-27 during R3D.2, a local documentation and owner-decision preparation
phase. The committed application is
`e1b572fbace62529e73df8e66a5b22888c22d28a`. The documentation edits prepared in R3D.2
are uncommitted proposals and were not part of that commit's hosted run. No new
application, database or live-model execution is claimed for this phase.

## Commit-scoped technical evidence

| Phase | Commit | Actual hosted result | Evidence scope |
| --- | --- | --- | --- |
| R1C | `6521b87` | [378 passed](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/38940470608) | Original clean-root PostgreSQL/offline baseline |
| R3B | `9b0c0df` | [616 passed](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/40437049577) | R2 application and versioned historical/current controls |
| R3C.2 | `e1b572f` | [682 passed](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/40516026765) | Explicit current evaluation contract 1.2; all 16 workflow steps succeeded |

R3C.2 also passed 682 tests in each independent local and remote fresh clone, with
isolated PostgreSQL, migrations/parity, offline evaluations, negative controls,
concurrency/recovery demos and security checks. Hosted execution reported one
existing Starlette/httpx warning; local JUnit runs reported ten warnings. Preserved
receipts establish these results. R3D.2 does not re-query GitHub or rerun that suite.
The canonical repository was verified PRIVATE in R3C.2; the owner changes
visibility directly.

## Frozen evidence and evaluation versions

The [historical live report](LIVE_EVALUATION_REPORT.md), milestone evidence, M0 risk
extract and [fingerprinted v1.2 specification](EVALUATION_CONTRACT_V1_2.md) are
preserved unchanged. Their statements that a correction was uncommitted or lacked
hosted verification describe their preparation-time state. The table above records
the subsequent R3C.2 verification. It does not change their observations or hashes.

The eight historical live executions retain separate raw-model, backend and
user-visible verdicts. Original S3 remains FAIL / PASS / FAIL; its separately
authorized HH:MM repair retest remains PASS / PASS / PASS. Original S5 remains
FAIL / PASS / PASS; its separate v1.1 retest remains PASS / PASS / PASS. No historical
execution is rescored with a newer grader. Original v1.0/v1.1 graders and fixtures
remain available; the default remains v1.0. Current offline evaluation must select
`--evaluation-contract 1.2` explicitly.

**GPT-6 Luna has not been live-evaluated under v1.2.** Passing offline fixtures or
safe deterministic rendering is not evidence of a correct raw model decision.
There is no repeated-sample statistical reliability estimate. The five-case smoke
dataset is small and heterogeneous, and its executions span different contracts.
PERF-001 remains an observed S4 latency outlier without an established SLO or
statistical characterization. UX-001 and AGENT-001 retests establish only their
observed sample outcomes. Production, clinical and regulatory claims remain outside
this synthetic prototype's scope.

The offline runner's legacy generated summary/help still says no live runner is
implemented. That wording is stale: `evaluations.live_runner` exists and requires
explicit live opt-in and single-scenario selection. Offline `NOT RUN` labels apply
to the invocation that produced them, not to all project history. R3D.2 leaves the
Python source and historical outputs unchanged; a later source wording correction
would need separate authorization and verification.

## Historical risk and owner decisions (closed 2026-10-30)

R3D.1 was accepted as an audit deliverable. The owner recorded the following
decisions on 2026-10-30; see the README [Security history](../README.md#security-history).

| Topic | Evidence | Decision |
| --- | --- | --- |
| Historical credentials | OpenAI and ElevenLabs keys revoked and rotated; owner reviewed provider usage for the exposure window with no unexpected activity; gitleaks v8.30.1 clean across all refs | CLOSED |
| Legacy records/audio | Owner attests synthetic demo material; no legacy records, audio or archives in any blob committed to this repository | CLOSED; no historical audio is redistributed |
| Legacy repository removal | The legacy repository, public for a period under a different name, was deleted; authenticated HTTP 404 observed | CLOSED; copies made while it was public cannot be recalled, and its keys are rotated |
| Current source isolation | Clean-root source/ancestry and exclusion checks verified; no legacy-data dependency | CLOSED |
| MIT/dependencies | MIT retained; 32 pinned distributions documented in [third-party notices](../THIRD_PARTY_NOTICES.md) | CLOSED; source-only distribution |

Reopen the relevant finding only if known active misuse, contrary real-data
provenance or a specific rights conflict becomes known. No release gate remains;
the owner changes repository visibility directly. See [the release checklist](RELEASE_READINESS.md)
and [security limitations](SECURITY_PRIVACY.md).
