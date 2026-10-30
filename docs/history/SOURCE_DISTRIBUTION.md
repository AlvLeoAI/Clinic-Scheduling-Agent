# Proposed source-only distribution

Prepared for local licensing review on 2026-10-27. **Licensing accepted by the owner
on 2026-10-30: source-only distribution under MIT, with dependency licenses documented
in [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).** This document defines the
source contents; it does not cover binary redistribution or deployment.

## Included contents

| Category | Proposed contents |
| --- | --- |
| Application source | Python backend, agent, CLI, evaluation and test code; migration source and template |
| Documentation and examples | Project documentation, inline diagrams, generated application OpenAPI, sanitized synthetic examples and previously reviewed public evidence extracts |
| Dependency declarations | pyproject.toml and requirements-foundation.lock, including existing development/test dependencies |
| Notices | Existing MIT LICENSE and [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md), including the complete notice for the incorporated Alembic template |
| Development instructions | Existing configuration examples, Compose/CI declarations and scripts; references to external runtimes are not copies of those runtimes |

Use an explicitly reviewed file manifest for any later release. A blanket archive
of the working directory is outside this scope. The existing .env.example is a
placeholder example, not permission to include a private environment file.

## Excluded contents

- Vendored wheels, site-packages, native shared libraries, package caches and venvs.
- Bundled runtime containers, image layers, executables and model weights.
- Legacy voice code, recordings, archives and unreviewed historical fixtures.
- Private reports, raw provider traces/transcripts and frozen private evaluation
  evidence, including the separately preserved 905-file evidence collection.
- Credentials, permanent .env files, private runtime configuration, local database
  state, local CLI/session state and generated verification artifacts.

Previously reviewed synthetic M5/M6 public extracts under docs/evidence remain
within the proposed source scope. They are distinct from raw private evidence.
The retired data/appointments.json marker contains empty collections and is not a
runtime data source. See [synthetic provenance](evidence/SYNTHETIC_PROVENANCE.md).
No historical voice material or private report is authorized for redistribution.

## Source ownership and notices

The existing MIT grant is preserved. On 2026-10-30 the copyright notice was
completed with the owner's full name: `Copyright (c) 2025 Alvaro Leopoldo Vazquez`. Original project material and third-party material have distinct
rights holders. An owner source-provenance attestation is recorded privately;
this is not independent verification of every contribution or a claim of exclusive
ownership. Licensing sign-off was given on 2026-10-30. Any newly identified copied work,
contributor right or contractual restriction requires specific review.

The known incorporated Alembic template has its upstream notice in
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md). The copyright year is
unchanged. No repository-wide claim that all included material
was authored exclusively by the project owner is made.

## Exact dependency reconciliation

The 32 pinned Python distributions below were reconciled with their installed
package metadata and license files during local review. There are eight direct
runtime requirements, two direct test/tool requirements, 18 transitive runtime
packages and four transitive test packages. The lock and dependency declarations
are unchanged. These are exact-version declarations for the reviewed Linux/Python
3.12 environment, not a guarantee for other platforms, extras or future resolutions.

With the single incorporated Alembic-template exception, the packages are
**referenced for separate installation**, not copied into this source candidate.
Their licenses remain their own. The license-text column identifies the files in
the relevant distribution's license metadata directory; no private runtime path is
published. The full Alembic notice is included because template material is actually
redistributed. The table does not substitute for license texts in a future bundle.

| Package | Pinned version | Dependency role | Declared license | Package license/attribution files |
| --- | --- | --- | --- | --- |
| alembic | 1.20.0 | direct runtime | MIT | `LICENSE` |
| annotated-doc | 0.0.5 | transitive runtime | MIT | `LICENSE` |
| annotated-types | 0.8.0 | transitive runtime | MIT | `LICENSE` |
| anyio | 4.15.1 | transitive runtime | MIT | `LICENSE` |
| certifi | 2026.7.22 | transitive runtime | MPL-2.0 | `LICENSE` |
| click | 8.5.0 | transitive runtime | BSD-3-Clause | `LICENSE.txt` |
| fastapi | 0.143.0 | direct runtime | MIT | `LICENSE` |
| greenlet | 3.5.6 | transitive runtime | MIT AND PSF-2.0 | `LICENSE`, `LICENSE.PSF` |
| h11 | 0.16.0 | transitive runtime | MIT | `LICENSE.txt` |
| httpcore | 1.0.9 | transitive runtime | BSD-3-Clause | `LICENSE.md` |
| httpx | 0.28.1 | direct runtime | BSD-3-Clause | `LICENSE.md` |
| idna | 3.20 | transitive runtime | BSD-3-Clause | `LICENSE.md` |
| iniconfig | 2.3.1 | transitive test | MIT | `LICENSE` |
| mako | 1.4.3 | transitive runtime | MIT | `LICENSE` |
| markupsafe | 3.0.4 | transitive runtime | BSD-3-Clause | `LICENSE.txt` |
| opentelemetry-api | 1.45.1 | transitive runtime | Apache-2.0 | `LICENSE` |
| packaging | 26.3 | transitive test | Apache-2.0 OR BSD-2-Clause | `LICENSE`, `LICENSE.APACHE`, `LICENSE.BSD` |
| pluggy | 1.6.0 | transitive test | MIT | `LICENSE` |
| psycopg | 3.3.6 | direct runtime | LGPL-3.0-only | `LICENSE.txt` |
| psycopg-binary | 3.3.6 | transitive runtime | LGPL-3.0-only | `LICENSE.txt` |
| pydantic | 2.14.1 | direct runtime | MIT | `LICENSE` |
| pydantic-core | 2.50.1 | transitive runtime | MIT | `LICENSE` |
| pydantic-settings | 2.15.0 | direct runtime | MIT | `LICENSE` |
| pygments | 2.21.0 | transitive test | BSD-2-Clause | `AUTHORS`, `LICENSE` |
| pytest | 9.1.1 | direct test/tool | MIT | `LICENSE` |
| python-dotenv | 1.2.4 | transitive runtime | BSD-3-Clause | `LICENSE` |
| ruff | 0.17.0 | direct test/tool | MIT | `LICENSE` |
| sqlalchemy | 2.0.54 | direct runtime | MIT | `AUTHORS`, `LICENSE` |
| starlette | 1.8.0 | transitive runtime | BSD-3-Clause | `LICENSE.md` |
| typing-extensions | 4.16.0 | transitive runtime | PSF-2.0 | `LICENSE` |
| typing-inspection | 0.4.4 | transitive runtime | MIT | `LICENSE` |
| uvicorn | 0.54.0 | direct runtime | BSD-3-Clause | `LICENSE.md` |

All 32 top-level declared licenses had local metadata and license evidence. This
does not make their entire native/embedded dependency trees MIT or exhaustively
reviewed. Exact component license evidence unavailable to the audit remains
**UNKNOWN**: notably the full version/license/notice mapping for shared libraries
inside psycopg-binary, and complete artifact-specific notices/linkage for embedded
components in Ruff and pydantic-core. Those binaries are excluded, not silently
cleared. No dependency is removed or replaced to obtain a different license result.

## Separate installation and future distribution modes

| Mode | Boundary |
| --- | --- |
| Source repository | Reviewed code/docs/examples, dependency declarations and applicable incorporated-material notices only; owner sign-off given 2026-10-30 |
| Dependency installation | Users obtain separate packages under their publishers' licenses; preserve those supplied notices. The project MIT license does not relicense them |
| Binary, wheelhouse or container distribution | Outside this proposal. Requires an exact artifact/component inventory, original license/attribution notices and applicable source-availability and replacement/relinking obligations |
| Hosted service | Outside this authorization. A source release does not authorize deployment or establish provider-contract, security, clinical or regulatory clearance |

For a future bundle, MIT/BSD notices, Apache notices and modification conditions,
PSF notices, MPL covered-source requirements and LGPL/GPL corresponding-source and
replacement/relinking requirements must be assessed for the actual distributed
material. Do not infer clearance from a root MIT file or this package table.
Relevant texts: [MIT](https://opensource.org/license/mit),
[BSD](https://opensource.org/license/bsd-3-clause),
[Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0),
[MPL 2.0](https://www.mozilla.org/en-US/MPL/2.0/),
[LGPL 3.0](https://opensource.org/license/lgpl-3-0) and
[Python license](https://docs.python.org/3/license.html).

The referenced PostgreSQL image, CPython and CI tools are separate artifacts;
their full contents are not licensed by this project's MIT notice. A Compose file
or CI image reference is not permission to redistribute all image layers.

Source-rights/licensing acceptance was given on 2026-10-30 for source-only
distribution. This is a scoped notice
remediation, not legal certification or a production-readiness claim. Existing
historical reports retain their original dates, results and evidence limitations.
