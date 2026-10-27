# Reproducibility and provenance

R1A exported an explicit reviewed working-tree allowlist, not Git HEAD, while preserving the original workspace privately. R1B initialized an independent root commit `6521b87bb98317ca02dc0174f3399fe9790ecb77`, without historical Git objects. R1C pushed that root to a standalone private staging repository and verified actual hosted CI and a fresh remote clone. R1D renamed the clean repository to the canonical name, redirected legacy writers, and quarantined/archived the original repository privately. No history rewrite or historical ancestry import was used.

Those stages are completed historical evidence, not actions repeated in R2D. R3B committed and verified those later R2 changes at `9b0c0df`. The current working tree contains the subsequent uncommitted R3C.1b correction; neither historical SHA identifies its executed source. Private per-file manifests and public component hashes in the [evaluation report](LIVE_EVALUATION_REPORT.md) distinguish them.

| Reproduction | Proof |
| --- | --- |
| M6 source-copy setup | Historical 378-test run; not a Git clone |
| R1B local fresh clone | Approved clean-root clone, isolated runtime and tests |
| R1C hosted / remote fresh clone | Approved root, 378 tests and 24 grader controls, migrations, offline evaluations and demos |
| R2C.1b current application | Local isolated source-copy run: 616 tests; no claim of current-tree hosted CI |
| R3B local / remote clone / hosted run | 616 tests in each at `9b0c0df`; [hosted receipt](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/40437049577) |
| R3C.1b grounding correction | Local offline verification only; no hosted run or remote clone of the uncommitted changes |

Future reproduction must use fresh private credentials, unique PostgreSQL storage and independent runtime, never original development data. R2 requires a dedicated test-only cluster at loopback port 15433 inside its verified runtime, with independently verified system identity. Stop if that endpoint belongs to an existing unidentified instance. Full tests include schema recreation and belong only in disposable verification environments. See [testing](../TESTING.md) and [runner isolation](AGENT_EVALUATION.md).

The retained scripts/reproduce_local.py exercises a working-tree copy, not a migration export or fresh-clone proof. It copies documentation directories and omits LICENSE from its temporary root-file selection; do not redistribute that temporary copy as a release package. The actual candidate retains MIT LICENSE. Cached dependencies/images in historical local runs do not prove cold offline availability.

Private .env, runtime credentials, traces and development state are ignored and excluded from publication review. R2D freezes evidence hashes without copying raw private reports into the candidate. A clean root does not resolve the historical P0 risk; [public release remains BLOCKED](RELEASE_READINESS.md).

The legacy repository subsequently became API-inaccessible (HTTP 404), and the owner confirmed intentional removal. This does not establish erasure of historical third-party copies or resolve P0.
