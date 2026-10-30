# Clinic Scheduling Agent

A synthetic text scheduling prototype built with FastAPI, PostgreSQL and validated agent tools. The backend owns scheduling rules, proposal state and atomic booking; a model cannot confirm an appointment.

Synthetic local demonstration: no real patients, clinics or production claims. All fixtures are generated (fictitious clinicians, UUID identifiers, fixed 2030 dates).

## What is demonstrated

- Chicago weekday scheduling, 30/60-minute visits, a 30-minute start grid, 24-hour notice and 90-day horizon.
- Immutable ten-minute booking proposals and an explicit `confirm <proposal_id>` action.
- PostgreSQL exclusion constraints, durable idempotency and recovery after a committed response is lost.
- Persistent, fenced chat orchestration using only catalog, availability and proposal tools.
- Independent backend tests, scripted agent evaluations and grader negative controls.
- Eight separately authorized live smoke executions, with failures and versioned retests preserved.

The offline CLI uses a deterministic fake provider with an explicit command grammar. It demonstrates validated tool flow and backend enforcement, not natural-language model reliability. Real `gpt-6-luna` smoke evaluations cover catalog, availability, proposals, ambiguity and unauthorized confirmation. Original S3 and S5 raw failures remain separate from successful corrected retests; backend enforcement and visible results are graded independently. See the [consolidated evaluation report](docs/LIVE_EVALUATION_REPORT.md).

The committed application at **`e1b572f`** passed **682 hosted tests** with explicit
**evaluation contract 1.2** ([R3C.2 hosted run](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/40516026765)); independent local and remote fresh clones also passed 682 tests each.
Historical hosted results remain **378 at root `6521b87`** and **616 at `9b0c0df`**.
These are offline application/fixture checks. GPT-6 Luna has **not** been live-evaluated
under v1.2; historical live results retain their original contracts and scores.
See [testing](TESTING.md) and [current status](docs/CURRENT_STATUS.md), including the
boundary between the verified commit and the proposed local documentation edits.

## Local setup and demos

Use Python 3.12 and the pinned `requirements-foundation.lock`; follow [local setup](docs/OPERATIONS.md). No OpenAI or ElevenLabs key is needed. The active server is `app.main:app`.

```bash
# After private environment, local PostgreSQL and pinned dependencies are prepared:
.venv/bin/python scripts/demo_concurrency.py --synthetic-only
.venv/bin/python -m cli --synthetic-only --scripted
.venv/bin/python -m cli --synthetic-only
```

Demos use only the guarded local `clinic_scheduling_test` database and an injected clock of 2030-01-07 15:00 UTC. The scripted demos clean only their own rows after verifying results. The interactive CLI retains its synthetic session in ignored mode-0600 `.local/cli_state.json`. Do not run DB demos/tests concurrently. The concurrency script refuses a nonempty appointment table and never resets it.

```text
catalog
availability 2030-01-09 00000000-0000-4000-8000-000000000101 00000000-0000-4000-8000-000000000201
propose 2030-01-09 09:00 00000000-0000-4000-8000-000000000101 00000000-0000-4000-8000-000000000201
confirm <proposal_id_returned_by_backend>
```

Confirmation bypasses the provider. A timeout is UNCERTAIN; retry the same command and private state to preserve its key. The CLI displays CONFIRMED only after retrieving the actual appointment.

## Evidence and documentation

- [Architecture](SYSTEM_DESIGN.md), [ADR index](docs/ADR_INDEX.md), [data integrity](docs/DATA_MODEL.md).
- [API/OpenAPI](docs/API_DESIGN.md), [operations and recovery](docs/OPERATIONS.md).
- [Agent/evaluation boundaries](docs/AGENT_EVALUATION.md), [M5 reconciliation](docs/M5_RECONCILIATION.md).
- [Tests and CI](TESTING.md), [security/privacy](docs/SECURITY_PRIVACY.md).
- [Acceptance matrix](docs/ACCEPTANCE_MATRIX.md), [release checklist](docs/RELEASE_READINESS.md).
- [M6 actual execution report](docs/evidence/M6_report.md), [accepted M5 evidence](docs/evidence/M5_report.md).

For a concise engineering overview and reproducible race demonstration, see the [portfolio summary](docs/PORTFOLIO_SUMMARY.md). [Reproducibility](docs/REPRODUCIBILITY.md) attributes each verification to its exact source commit.

## Security history

This repository starts from a clean root commit (`6521b87`, 2026-10-16). An earlier
prototype repository, public for a period under a different name, had committed archives
containing OpenAI and ElevenLabs API keys, along with demo appointment records and audio
from a retired voice version.

What was done:

- The exposed OpenAI and ElevenLabs keys were revoked and rotated.
- The project was rebuilt from a reviewed file allowlist. No legacy commits, archives,
  audio or appointment records were carried over, and the legacy repository was deleted.
- gitleaks v8.30.1 reports no findings across every ref of this repository. Every blob
  ever committed here is text: no audio, archives or credential files.
- CI runs a current-tree secret and synthetic-fixture check on every push.

What remains: nothing in this repository. Provider usage for the exposure window was
reviewed with no unexpected activity.

## Provenance

Legacy voice code, audio dependencies, clinic/insurance fixtures, historical appointment records, Git objects and private development state are excluded from this candidate. The original workspace and its accepted private evidence remain preserved separately. The only data/appointments.json file here is an empty retired marker required by retained static checks; it is not a runtime seed.

The source is distributed under the MIT license; dependencies are installed separately under their own licenses, listed in [third-party notices](THIRD_PARTY_NOTICES.md). Product contracts are unchanged; see the [approved product baseline](docs/ARCHITECTURE_BASELINE.md) and [synthetic evidence provenance](docs/evidence/SYNTHETIC_PROVENANCE.md). Public milestone reports are labeled extracts of historical results, not new executions. Raw ledgers, internal execution prompts and local paths are withheld.

Use only independently isolated synthetic test resources for future reproduction. Never reuse development databases. See the [release checklist](docs/RELEASE_READINESS.md) for remaining, non-security limitations.
