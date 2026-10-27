# Reproducibility and provenance

R1A exported an explicit reviewed working-tree allowlist, not Git HEAD, while preserving the original workspace privately. R1B initialized an independent root commit `6521b87bb98317ca02dc0174f3399fe9790ecb77`, without historical Git objects. R1C pushed that root to a standalone private staging repository and verified actual hosted CI and a fresh remote clone. R1D renamed the clean repository to the canonical name, redirected legacy writers, and quarantined/archived the original repository privately. No history rewrite or historical ancestry import was used.

Those stages are completed historical evidence, not actions repeated in R2D. The current working tree includes later uncommitted R2 changes; the root SHA alone cannot identify their executed versions. Private per-file manifests and public component hashes in the [evaluation report](LIVE_EVALUATION_REPORT.md) distinguish them.

| Reproduction | Proof |
| --- | --- |
| M6 source-copy setup | Historical 378-test run; not a Git clone |
| R1B local fresh clone | Approved clean-root clone, isolated runtime and tests |
| R1C hosted / remote fresh clone | Approved root, 378 tests and 24 grader controls, migrations, offline evaluations and demos |
| R2C.1b current application | Local isolated source-copy run: 616 tests; no claim of current-tree hosted CI |
| Current R2 fresh remote clone / hosted run | NOT RUN; requires separately approved source snapshot and submission |

Future reproduction must use fresh private credentials, unique PostgreSQL storage and independent runtime, never original development data. R2 requires a dedicated test-only cluster at loopback port 15433 inside its verified runtime, with independently verified system identity. Stop if that endpoint belongs to an existing unidentified instance. Full tests include schema recreation and belong only in disposable verification environments. See [testing](../TESTING.md) and [runner isolation](AGENT_EVALUATION.md).

The retained scripts/reproduce_local.py exercises a working-tree copy, not a migration export or fresh-clone proof. It copies documentation directories and omits LICENSE from its temporary root-file selection; do not redistribute that temporary copy as a release package. The actual candidate retains MIT LICENSE. Cached dependencies/images in historical local runs do not prove cold offline availability.

Private .env, runtime credentials, traces and development state are ignored and excluded from publication review. R2D freezes evidence hashes without copying raw private reports into the candidate. A clean root does not resolve the historical P0 risk; [public release remains BLOCKED](RELEASE_READINESS.md).
