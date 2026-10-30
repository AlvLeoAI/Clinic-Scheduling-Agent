# M3 — Atomic confirmation and recovery — historical public extract

> Superseded on 2026-10-30: see README [Security history](../../../README.md#security-history).

Public-safe extract prepared during R1A on 2026-10-16. Original private report and exact ledgers remain unchanged outside this candidate. Results below were recorded in the original milestone; they were not rerun from this candidate. Owner has accepted M0–M6 local technical gates. Public release remains BLOCKED by unresolved historical privacy/security and separate verification/authorization gates.

Recorded final suite: 234 passed, 0 failed, 0 skipped, one inherited warning. The 90 M3 cases added immutable proposal lifecycle, owning bearer checks, TTL/supersede/terminal state enforcement, direct confirmation, durable fingerprints/results and appointment retrieval.

Real PostgreSQL coordinated races used independent connections, including five repeated overlap races with one 201, one actual exclusion 23P01/SLOT_TAKEN 409 and one appointment. Adjacent/non-overlapping and separate-practitioner bookings passed. Sequential/concurrent key replay and different-payload reuse were exercised.

Test-only failures covered precommit rollback, committed response loss, unknown commit acknowledgement and retry after server-raised 40001. Independent DB reads established state; fresh app/engine with the original key recovered the stored result without duplicate booking. These were not OS/PostgreSQL process-crash tests; a separate natural deadlock scenario was NOT RUN. No public failure/debug endpoint exists. See [data guarantees](../DATA_MODEL.md) and [recovery](../../API_DESIGN.md).
