# Release-readiness checklist

**Public release: no open gates (2026-10-30).** Historical security (SEC-01, SEC-02)
and licensing are closed by owner decision; see the README
[Security history](../README.md#security-history). The owner changes repository
visibility directly. Remaining NOT RUN rows below are scope limitations of a
synthetic prototype, not release gates.

| Check | Status | Evidence boundary / next action |
| --- | --- | --- |
| R1A preservation and reviewed export | PASS | Accepted private manifests and explicit source allowlist |
| R1B independent root | PASS | Root `6521b87`, no imported historical ancestry |
| R1C hosted CI / fresh-clone reproduction | PASS | 378 tests at `6521b87`, isolated PostgreSQL and offline checks |
| R1D private cutover | PASS (historical) | Legacy private/archived at cutover; later HTTP 404 and owner-confirmed removal. Historical rollback must not assume that repository still exists |
| R3B hosted CI / fresh-clone reproduction | PASS | 616 tests at `9b0c0df`; commit-scoped evidence retained |
| R3C.2 hosted CI / fresh-clone reproduction | PASS | 682 tests at `e1b572f`, explicit v1.2; local and remote clones passed; [actual run](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/40516026765) |
| Historical live results and graders | PASS (preserved evidence) | Eight executions; original S3 and S5 failures and separate retests remain unchanged; v1.0/v1.1 preserved |
| Live model verification under v1.2 | NOT RUN | Offline hosted success does not establish live behavior; any new experiment needs separate approval |
| Historical security/privacy audit | PASS | R3D.1 audit deliverable; owner decisions recorded and gates closed 2026-10-30 |
| SEC-01 credential residual risk | CLOSED | OpenAI and ElevenLabs keys revoked and rotated; owner reviewed provider usage for the exposure window with no unexpected activity; gitleaks v8.30.1 clean across all refs |
| SEC-02 provenance and exclusion | CLOSED | No legacy records, audio, archives or credential files in any committed blob; current fixtures are generated synthetic data |
| Historical copies and private retention | CLOSED | Legacy repository deleted; copies made while it was public cannot be recalled and its keys are rotated. Private evidence stays with the owner outside this repository |
| Included-source rights and redistribution | CLOSED | Source-only distribution under MIT; dependency licenses in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and [source scope](SOURCE_DISTRIBUTION.md) |
| Documentation commits after `e1b572f` | PASS | Hosted CI passed 737 tests at `fa6b63d` ([run](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/41122901875)) |
| Final repository identity/ref preflight | PASS | 2026-10-30: refs are `main` and merged PR #1 only; no tags, releases, issues or artifacts; all Actions run logs scanned with no secrets or personal data |
| Final publication | OWNER ACTION | The owner changes repository visibility; no further documentation gate |
| PERF-001 / repeated-sample latency | NOT RUN (open finding) | S4 took 22.597177 seconds; no statistical characterization or approved SLO; keep limitation visible |
| Production, clinical or regulatory certification | NOT RUN | Outside the synthetic source demonstration's scope; no such claim is permitted |

Historical security and licensing have no remaining owner decisions. Reopen the
relevant finding only if specific contrary provenance, an accessible sensitive copy
or a rights conflict becomes known.

Before changing visibility, confirm that hosted CI passed on the final commit.

Maturity: synthetic local demonstration prototype. Typed rendering, bounded fixture
grammar, character-based context accounting, per-phase timeout, buffered response
checks and session-expiry recovery remain limitations. There is no retention/purge
implementation or production load/OS-crash certification. Single live observations
are not statistical reliability estimates.

Original reports remain private and unchanged. Public-facing summaries contain no
raw transcripts, operational identifiers or private evidence links. See
[current evidence scope](CURRENT_STATUS.md), [live limitations](LIVE_EVALUATION_REPORT.md),
[acceptance matrix](ACCEPTANCE_MATRIX.md), [security](SECURITY_PRIVACY.md) and
[reproducibility](REPRODUCIBILITY.md).
