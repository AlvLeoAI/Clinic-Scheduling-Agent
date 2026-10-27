# Testing and evidence boundaries

| Evidence | Observed result | Scope |
| --- | --- | --- |
| M0–M6 / clean-root R1B reproduction | 378 passed | Historical local execution; original reports preserved |
| R1C hosted GitHub Actions | 378 passed, 0 failed/skipped | Approved root `6521b87`; real PostgreSQL service, 24 original grader controls, offline cases and demos |
| R1C remote fresh clone | PASS | Root-commit reproduction with independent storage/runtime/database |
| R2C.1b full local suite | 616 passed, 0 failed/errors/skips, 5 warnings | Accepted uncommitted R2 source; isolated PostgreSQL and blocked real HTTP |
| R2C.1b historical controls | 25 passed | 24 original controls plus the existing live-grader test |
| R2C.1b v1.1 controls | 52 passed | 45 adversarial and seven positive/version/clarification controls |
| R2C.2 preflight controls | 216 passed | Targeted offline controls; 46 PostgreSQL tests deselected in that command; separate mocked PostgreSQL checks recorded |
| Current R2 code on hosted CI | NOT RUN | Hosted root evidence does not validate newer work |

R2D performs documentation, hash, link and current-tree security checks only. It does not rerun application/database tests, migrations or demos. See [live evaluation evidence](docs/LIVE_EVALUATION_REPORT.md) for separately authorized paid runs; no future live call is authorized here.

## Reproduce offline checks

Use Python 3.12, the pinned lockfile and a new disposable synthetic PostgreSQL runtime following [operations](docs/OPERATIONS.md) and [R2 isolation](docs/AGENT_EVALUATION.md). The full suite includes a migration round trip that rebuilds its guarded schema: never run it against a database whose state must be preserved. Use a disposable verification copy and private output paths so generated regression ledgers cannot overwrite accepted evidence. Run stateful commands sequentially.

```bash
CLINIC_BOOKING_EVIDENCE_FILE=M6_booking_regression_cases.json \
CLINIC_AGENT_EVIDENCE_FILE=M6_m4_regression_cases.json .venv/bin/pytest -q -p tests.r2a_offline_guard
.venv/bin/python -m evaluations.runner --evaluation-contract 1.1 --output-dir test-results/verification/evals
.venv/bin/python scripts/demo_concurrency.py --synthetic-only --evidence test-results/verification/concurrency.json
.venv/bin/python -m cli --synthetic-only --scripted --evidence test-results/verification/cli.json
.venv/bin/ruff check app cli scripts alembic tests evaluations
.venv/bin/ruff format --check app cli scripts alembic tests evaluations
.venv/bin/alembic check
.venv/bin/alembic current
.venv/bin/python -m scripts.check_synthetic
.venv/bin/python -m scripts.check_docs
```

The HTTP-denial pytest plugin allows fakes, MockTransport and in-process TestClient, never real provider requests. Default pytest excludes agent_live. Collection is not execution. The live runner exists but requires explicit owner authorization, runtime opt-in and single-scenario selection.

Select contract **1.1 explicitly** for the current application. Historical 1.0 remains the default and is intentionally incompatible with new availability guidance: three M5 visible cases and R2 S2 fail its old finite grammar. Legacy tests retain frozen fixtures; this incompatibility is asserted rather than hidden. M5 v1.1 fixture results preserve 15 raw PASS / 9 intentionally bad raw FAIL / 1 absent-output NOT RUN, with 25 backend and 25 visible PASS. These are fixture dispositions, not model reliability.

The unchanged scripts/check_docs checker validates links, OpenAPI and M5 evidence, but its printed hosted_ci=NOT RUN and M5 agent_live=NOT RUN are historical/static labels. They do not query GitHub or supersede R1C/live receipts. Do not interpret them as current execution status. [Release gates](docs/RELEASE_READINESS.md) separate all evidence scopes.
