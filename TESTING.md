# Testing and evidence boundaries

The source suite has recorded M0–M6 local acceptance. Its final original run was 378 passed, 0 failed, 0 skipped, with one inherited Starlette/httpx deprecation warning. These are historical results, not tests executed from this R1A candidate.

R1A permits static preparation only. Do not run application/database tests or demos until R1B is explicitly authorized. After authorization, use a disposable verification copy or later a genuine clean-root clone, a fresh venv, a new private environment, a unique Compose project/free port/new volume, and only its own synthetic test database. Clear inherited database/vendor settings. Never reuse original databases.

Planned commands in that verification copy, after isolated setup:

```bash
CLINIC_BOOKING_EVIDENCE_FILE=M6_booking_regression_cases.json \
CLINIC_AGENT_EVIDENCE_FILE=M6_m4_regression_cases.json .venv/bin/pytest -q
.venv/bin/python -m evaluations.runner --output-dir test-results/r1b/evals
.venv/bin/python scripts/demo_concurrency.py --synthetic-only --evidence test-results/r1b/concurrency.json
.venv/bin/python -m cli --synthetic-only --scripted --evidence test-results/r1b/cli.json
.venv/bin/ruff check app cli scripts alembic tests evaluations
.venv/bin/ruff format --check app cli scripts alembic tests evaluations
.venv/bin/alembic check
.venv/bin/alembic current
.venv/bin/python -m scripts.check_synthetic
.venv/bin/python -m scripts.check_docs
```

Run stateful commands sequentially. A retained migration test rebuilds only the guarded test schema. Pytest regression fixtures create M6-named evidence under docs/evidence in the disposable verification copy; do not copy these generated files back into the sealed candidate without review. Eval/demo flags above keep other output under ignored test-results.

Unit tests do not connect to PostgreSQL; postgres requires it. api and agent_offline categories overlap; default pytest excludes reserved agent_live. No live runner exists. Collection alone is not execution. Record exact commands, exit codes, actual pass/fail/skip counts and warnings.

The retained .github/workflows/ci.yml uses pinned actions, PostgreSQL, migrations, Ruff, full tests including 24 grader controls, offline evaluations and both demos without vendor credentials. Local YAML/static review is distinct from hosted execution. Hosted CI and all fresh-clone verification remain NOT RUN.

M5's 25 scripted cases preserve raw 15 PASS / 9 intentional FAIL / 1 NOT RUN separately from backend/visible 25 PASS each. See [provenance](docs/evidence/SYNTHETIC_PROVENANCE.md), [reconciliation](docs/M5_RECONCILIATION.md), [M6 historical extract](docs/evidence/M6_report.md), [operations](docs/OPERATIONS.md) and [release gates](docs/RELEASE_READINESS.md). Pattern checks cannot establish global privacy clearance.
