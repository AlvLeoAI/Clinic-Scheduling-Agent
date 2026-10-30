# M2 — Deterministic scheduling — historical public extract

> Superseded on 2026-10-30: see README [Security history](../../README.md#security-history).

Public-safe extract prepared during R1A on 2026-10-16. Original private report and exact ledgers remain unchanged outside this candidate. Results below were recorded in the original milestone; they were not rerun from this candidate. Owner has accepted M0–M6 local technical gates. Public release remains BLOCKED by unresolved historical privacy/security and separate verification/authorization gates.

Recorded final suite: 144 passed, 0 failed, 0 skipped, one inherited warning. This includes 46 foundation tests and 98 scheduling/availability tests. Real PostgreSQL supplied catalog/types/weekly schedules and confirmed reservations; the GET availability contract remained read-only.

Coverage includes business-hour/weekend/grid boundaries, 30/60-minute types, inclusive elapsed 24-hour/90-day limits, Chicago DST, overlap/adjacency, different practitioners, exhausted days, invalid catalog IDs, sorted results and no query mutation. No booking or agent feature was introduced by M2. See [approved rules](../ARCHITECTURE_BASELINE.md).
