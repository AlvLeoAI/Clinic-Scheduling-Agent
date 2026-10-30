# Release-readiness checklist

**Public release: BLOCKED.** R3D.1 was accepted as an audit deliverable; owner risk
acceptance remains UNDECIDED. R3D.2 authorizes local documentation and decision
preparation only. No commit, push, publication, visibility change, deployment or
provider call is authorized. PRIVATE visibility is the last verified R3C.2 state,
not a fresh remote observation in this phase.

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
| Historical security/privacy audit | PASS (deliverable only) | R3D.1 evidence, limitations and proposed dispositions reviewed; not risk acceptance |
| SEC-01 credential residual risk | BLOCKED | Owner decision UNDECIDED; recorded rotation/revocation attestation, uncertain historical usage-review outcome |
| SEC-02 provenance and exclusion | BLOCKED | Owner decision UNDECIDED; synthetic-provenance attestation and clean-source exclusion are separate forms of evidence |
| Historical copies and private retention | BLOCKED | Owner must decide known-sharing/residual-copy disposition and private custodian/review scope; preserve all 905 frozen files |
| Included-source rights and redistribution | BLOCKED | Owner approval UNDECIDED; MIT retained, dependency licenses separate; proposed source-only scope |
| R3D.2 proposed documentation commit / hosted validation | NOT RUN | Local edits are outside `e1b572f`; review final diff/manifest and explicitly authorize the next private commit/push gate |
| Final repository identity/visibility/ref preflight | NOT RUN | Revalidate intended clean repository and exact reviewed commit before a separately authorized remote action |
| Final publication authorization | BLOCKED | Requires explicit owner decisions and a separate instruction naming the final approved commit and publication scope |
| PERF-001 / repeated-sample latency | NOT RUN (open finding) | S4 took 22.597177 seconds; no statistical characterization or approved SLO; keep limitation visible |
| Production, clinical or regulatory certification | NOT RUN | Outside the synthetic source demonstration's scope; no such claim is permitted |

The minimum remaining owner decisions are explicit SEC-01 and SEC-02 residual-risk
dispositions, known sharing/retention choices, included-source rights and license
approval, and an overall scoped acceptance. All are UNDECIDED in the private package.
No proof of eliminating every unknown outside copy is demanded. A known active
incident or actual rights deficiency cannot be cleared by a generic acceptance.

After owner review, a separately authorized private commit/push phase must verify
the exact file manifest, preserve all historical evidence and private configuration,
run applicable offline documentation/security checks and hosted CI, and verify a
fresh remote clone of that final commit. Existing 682-test proof applies only to
`e1b572f`. Any unexpected source change or failed gate requires review before
publication. None of these future operations is authorized by this checklist.

Maturity: synthetic local demonstration prototype. Typed rendering, bounded fixture
grammar, character-based context accounting, per-phase timeout, buffered response
checks and session-expiry recovery remain limitations. There is no retention/purge
implementation or production load/OS-crash certification. Single live observations
are not statistical reliability estimates. PASS never waives a blocked owner gate.

Original reports remain private and unchanged. Public-facing summaries contain no
raw transcripts, operational identifiers or private evidence links. See
[current evidence scope](CURRENT_STATUS.md), [live limitations](LIVE_EVALUATION_REPORT.md),
[acceptance matrix](ACCEPTANCE_MATRIX.md), [security](SECURITY_PRIVACY.md) and
[reproducibility](REPRODUCIBILITY.md).
