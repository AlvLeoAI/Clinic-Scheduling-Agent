# Release-readiness checklist

**Public release gate: BLOCKED.** Owner acceptance of M0–M6 local technical gates and R1A preparation authorization do not authorize publication or Git operations.

| Check | Status | Required disposition |
| --- | --- | --- |
| Historical Git credential/audio/privacy exposure | BLOCKED / P0 | Owner disposition and audit. Clean-root preparation does not erase old clones, forks or caches. |
| R1A owner acceptance | NOT RUN | Review the private preservation, publication manifest and R1A report. |
| New Git root / initial commit | NOT RUN | Separate R1B authorization and ancestry/object-isolation checks. |
| Runtime/setup from candidate | NOT RUN | Isolated resources and actual retained regression/evaluation/demo results. |
| Local/GitHub fresh clone | NOT RUN | Actual clone proof, never a source-copy claim. |
| Hosted GitHub Actions | NOT RUN | Local workflow exists; no hosted execution performed. |
| GitHub migration, visibility or name cutover | NOT RUN | Separate owner authorization; original private repository unchanged. |
| Public evidence and redistribution review | Pending owner acceptance | Public extracts and synthetic artifacts reviewed locally; MIT LICENSE preserved, dependency attribution not independently certified. |
| Live model evaluations | NOT RUN | Separate approval/configuration; no reliability or cost claims from scripted fixtures. |

This remains a synthetic local prototype with typed/template replies, bounded fixture grammar, character-based context accounting, per-phase provider timeout and buffered response bounds, no purge policy, same-session recovery only before expiry, and no production/load/OS-crash certification. No clinical, regulatory or production-readiness claim is made.

The private R1A report and publication manifest are outside this candidate. Static content review does not clear these release gates. See [AC matrix](ACCEPTANCE_MATRIX.md), [security limits](SECURITY_PRIVACY.md) and [reproducibility](REPRODUCIBILITY.md).
