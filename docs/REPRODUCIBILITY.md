# Reproducibility and candidate provenance

This R1A candidate was constructed from an explicit reviewed working-tree file allowlist, not Git HEAD. It has no .git directory, environment file, venv, database volume or private CLI state. Original application, schema, migration, lock, tests and fixture bytes remain unchanged. Candidate-only documentation extracts are tracked in the private R1A publication manifest.

Original M6 evidence records an isolated source-copy setup: new private environment/venv, offline cached pinned dependencies, fresh project/port/PostgreSQL volume, migrations, seed twice, 378 tests, offline evaluations and demos passed. This was not a Git clone. See the [historical M6 extract](evidence/M6_report.md).

R1A runtime/setup tests, local fresh clone, GitHub fresh clone and hosted Actions are NOT RUN. Later R1B must record actual execution from isolated resources after separate authorization. It must not inherit original DB URLs or reuse original databases. Package/image availability in a cold environment has not been established by cached M6 execution.

The retained scripts/reproduce_local.py may later exercise an isolated working-tree copy with its own random project and scoped cleanup. It is not a migration copier or fresh-clone verifier: it copies documentation directories and omits LICENSE from its temporary root-file selection. Its output must remain under ignored test-results and must not be redistributed as a release package. The actual release candidate retains the root MIT LICENSE.

No dependency download, provider call, Git initialization, clone, push or GitHub operation was performed for R1A. Publication remains [BLOCKED](RELEASE_READINESS.md), including unresolved historical privacy disposition and missing owner authorization.
