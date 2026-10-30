# Reproducibility and provenance

R1A exported an explicit reviewed working-tree allowlist, not Git HEAD, while preserving the original workspace privately. R1B initialized an independent root commit `6521b87bb98317ca02dc0174f3399fe9790ecb77`, without historical Git objects. R1C pushed that root to a standalone private staging repository and verified actual hosted CI and a fresh remote clone. R1D renamed the clean repository to the canonical name, redirected legacy writers, and quarantined/archived the original repository privately. No history rewrite or historical ancestry import was used.

Those stages are completed historical evidence, not actions repeated in R2D. R3B committed and verified the later R2 changes at `9b0c0df`. R3C.2 committed the R3C.1b grounding correction at `e1b572fbace62529e73df8e66a5b22888c22d28a` and verified local and remote fresh clones plus hosted CI. Private per-file manifests and the preserved [evaluation report](LIVE_EVALUATION_REPORT.md) distinguish historical runs. [Current status](CURRENT_STATUS.md) records the later receipts and the separate, uncommitted R3D.2 documentation proposal.

| Reproduction | Proof |
| --- | --- |
| M6 source-copy setup | Historical 378-test run; not a Git clone |
| R1B local fresh clone | Approved clean-root clone, isolated runtime and tests |
| R1C hosted / remote fresh clone | Approved root, 378 tests and 24 grader controls, migrations, offline evaluations and demos |
| R2C.1b quality correction | Historical local isolated source-copy run: 616 tests; subsequently committed and verified in R3B |
| R3B local / remote clone / hosted run | 616 tests in each at `9b0c0df`; [hosted receipt](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/40437049577) |
| R3C.1b grounding correction | Historical local 682-test verification; subsequently committed and verified in R3C.2 |
| R3C.2 local / remote clone / hosted run | 682 tests in each at `e1b572f`, explicit v1.2; [hosted receipt](https://github.com/AlvLeoAI/Clinic-Scheduling-Agent/actions/runs/40516026765) |

Future reproduction must use fresh private credentials, unique PostgreSQL storage and independent runtime, never original development data. R2 requires a dedicated test-only cluster at loopback port 15433 inside its verified runtime, with independently verified system identity. Stop if that endpoint belongs to an existing unidentified instance. Full tests include schema recreation and belong only in disposable verification environments. See [testing](../TESTING.md) and [runner isolation](AGENT_EVALUATION.md).

The retained scripts/reproduce_local.py exercises a working-tree copy, not a migration export or fresh-clone proof. It copies documentation directories and omits LICENSE from its temporary root-file selection; do not redistribute that temporary copy as a release package. The actual candidate retains MIT LICENSE. Cached dependencies/images in historical local runs do not prove cold offline availability.

Private .env, runtime credentials, traces and development state are ignored and excluded from publication review. R2D freezes evidence hashes without copying raw private reports into the candidate. The historical exposure was closed on 2026-10-30; see the README [Security history](../README.md#security-history).

The legacy repository subsequently became API-inaccessible (HTTP 404), and the owner confirmed intentional removal. Copies made while it was public cannot be recalled; its exposed keys were rotated.
