# M1 — Backend foundation — historical public extract

> Superseded on 2026-10-30: see README [Security history](../../README.md#security-history).

Public-safe extract prepared during R1A on 2026-10-16. Original private report and exact ledgers remain unchanged outside this candidate. Results below were recorded in the original milestone; they were not rerun from this candidate. Owner has accepted M0–M6 local technical gates. Public release remains BLOCKED by unresolved historical privacy/security and separate verification/authorization gates.

Recorded final suite: 46 passed, 0 failed, 0 skipped, one inherited warning. FastAPI/configuration, Pydantic contracts, PostgreSQL ten-table foundation and Alembic revision 0001 were established. New dev migration/seed twice, test downgrade/reapply and metadata parity passed; no later milestone migration was added.

Vendor credentials are unnecessary for foundation/booking. Session lifetime was approved as 24 hours without sliding renewal. Catalog and schedules are artificial. See [data model](../DATA_MODEL.md), [operations](../OPERATIONS.md) and [API](../API_DESIGN.md).
