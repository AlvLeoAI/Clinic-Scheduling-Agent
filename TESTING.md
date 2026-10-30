# Testing and evidence boundaries

| Evidence | Observed result | Scope |
| --- | --- | --- |
| M0–M6 / clean-root R1B reproduction | 378 passed | Historical local execution; original reports preserved |
| R1C hosted GitHub Actions | 378 passed, 0 failed/skipped | Approved root `6521b87`; real PostgreSQL service, 24 original grader controls, offline cases and demos |
| R1C remote fresh clone | PASS | Root-commit reproduction with independent storage/runtime/database |
| R2C.1b full local suite | 616 passed, 0 failed/errors/skips, 5 warnings | Accepted R2 source, subsequently committed in `9b0c0df`; isolated PostgreSQL and blocked real HTTP |
| R2C.1b historical controls | 25 passed | 24 original controls plus the existing live-grader test |
| R2C.1b v1.1 controls | 52 passed | 45 adversarial and seven positive/version/clarification controls |
| R2C.2 preflight controls | 216 passed | Targeted offline controls; 46 PostgreSQL tests deselected in that command; separate mocked PostgreSQL checks recorded |
| R3B hosted GitHub Actions | 616 passed | Commit `9b0c0df`, [run 40437049577](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/40437049577), actual PostgreSQL/offline execution |
| R3B local and remote fresh clones | 616 passed in each | Independently isolated Git storage, runtime and PostgreSQL |
| R3C.1b full local suite | 682 passed, 0 failed/errors/skips, 10 warnings | Isolated PostgreSQL, explicit v1.2, real HTTP blocked; 2026-10-27 |
| R3C.2 precommit / local fresh clone / remote fresh clone | 682 passed in each, 10 warnings each | Exact accepted application content committed at `e1b572f`; independent Git storage, runtime and PostgreSQL |
| R3C.2 hosted GitHub Actions | 682 passed, 1 warning in 35.30s | Commit `e1b572f`, [run 40516026765](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/40516026765); all 16 steps succeeded, explicit v1.2 and real PostgreSQL |
| R3D.2 documentation reconciliation | Local documentation review only | No full application suite, database operation or fresh hosted run; proposed edits are outside the verified commit |

R2D performed documentation, hash, link and current-tree security checks only. R3B subsequently ran the full suite and demos on `9b0c0df`; R3C.2 did so on `e1b572f`. No live GPT-6 Luna run used v1.2. See [live evaluation evidence](docs/history/LIVE_EVALUATION_REPORT.md) for separately authorized paid runs and [current status](docs/history/CURRENT_STATUS.md) for later commit-scoped receipts; no future live call is authorized here.

## Reproduce offline checks

Use Python 3.12, the pinned lockfile and a new disposable synthetic PostgreSQL runtime following [operations](docs/history/OPERATIONS.md) and [R2 isolation](docs/history/AGENT_EVALUATION.md). The full suite includes a migration round trip that rebuilds its guarded schema: never run it against a database whose state must be preserved. Use a disposable verification copy and private output paths so generated regression ledgers cannot overwrite accepted evidence. Run stateful commands sequentially.

```bash
CLINIC_BOOKING_EVIDENCE_FILE=M6_booking_regression_cases.json \
CLINIC_AGENT_EVIDENCE_FILE=M6_m4_regression_cases.json .venv/bin/pytest -q -p tests.r2a_offline_guard
.venv/bin/python -m evaluations.runner --evaluation-contract 1.2 --output-dir test-results/verification/evals
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

Select contract **1.2 explicitly** for current application verification. The default
remains historical 1.0. Frozen v1.0/v1.1 implementation and fixture controls are
retained; the current no-proposal confirmation wording intentionally fails both old
grammars. Historical availability wording differs between 1.0 and 1.1 as before.
These explicit compatibility checks do not rescore historical live records. M5
fixture PASS can include an intentionally incorrect raw decision; report each layer
separately. See [the v1.2 contract](docs/EVALUATION_CONTRACT_V1_2.md).

The local `scripts/check_docs` checker validates links, OpenAPI and accepted M5
evidence. Its `hosted_ci_query` is **NOT QUERIED BY THIS LOCAL CHECK**; commit-scoped
hosted evidence is documented above from preserved R1C/R3B/R3C.2 receipts. The nested M5
`agent_live=NOT RUN` applies only to that historical offline reconciliation.
Historical security status is recorded in the README [Security history](README.md#security-history); see also the [release checklist](docs/history/RELEASE_READINESS.md).

R3C.1b count reconciliation: the 616-test baseline is retained, plus 17 focused
proposal-grounding cases (including seven first added in R3C.1), 47 independent
v1.2 controls, one version-dispatch check and one additional mocked-runner contract
parameter: **682 total**. The original four reproduction failures now pass. The
first full attempt had 673 passes and one old-default-contract integration failure;
explicit 1.2 selection corrected that test's version attribution without weakening
its assertions. The final suite had ten warnings: one inherited Starlette/httpx
deprecation and nine JUnit record_property warnings. Historical v1.0/v1.1 fixtures
remain unchanged. None of these tests is a paid model execution.
