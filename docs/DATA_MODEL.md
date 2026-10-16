# PostgreSQL data model and guarantees

Alembic revision `0001` creates ten core tables and `btree_gist`. No M2–M6 schema migration was added. Instants are timezone-aware `TIMESTAMPTZ`; sessions use UUIDs and store only SHA-256 hashes of 256-bit random bearer tokens.

| Table | Meaning / key invariants |
| --- | --- |
| `clinics` | One artificial clinic and fixed Chicago timezone. |
| `practitioners` | Two active synthetic clinicians scoped to clinic. |
| `appointment_types` | Artificial visit codes with 30/60-minute duration. |
| `weekly_schedules` | ISO weekdays 1–5 and weekly working intervals per practitioner. |
| `chat_sessions` | Token hash, fixed expiry, active turn, lease deadline and monotonically increasing fence. |
| `chat_turns` | UNIQUE(session_id,client_message_id), request fingerprint, status, trace and stored assistant message. |
| `conversation_items` | Ordered JSONB items; UNIQUE(turn_id,sequence), correlated call-ID uniqueness and composite owner FK. |
| `booking_proposals` | Immutable booking snapshot, TTL/status, nullable unique source_turn_id and one-PENDING-per-session partial index. |
| `appointments` | Actual confirmed reservation; unique proposal and composite FK to its exact booking snapshot. |
| `idempotency_records` | UNIQUE(session_id,key), stable fingerprint, original HTTP status/body and trace. |

The final overlap authority is GiST exclusion of `(practitioner_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)`. Adjacent intervals and different practitioners may coexist. UNIQUE(source_turn_id) prevents a second proposal creation effect for one chat turn; journaled results also prevent replay execution. Composite FKs enforce session/turn ownership and appointment/proposal snapshot agreement.

Application services enforce business hours, grid, active catalog, notice/horizon, immutable proposal fields and one-way PENDING→CONFIRMED/CONFLICTED/EXPIRED/SUPERSEDED transitions. No database trigger enforcing every business policy or field immutability is claimed. Direct privileged SQL is outside the service safety boundary.

Confirmation locks session then proposal, checks durable replay/fingerprint and policy/TTL/occupancy, inserts under a savepoint, and rechecks deadlines after an insert wait. `23P01` from `appointments_no_overlap` rolls back that insert, then records CONFLICTED/SLOT_TAKEN in the valid outer transaction. Appointment, CONFIRMED and durable result commit together. Unknown commit acknowledgement yields retryable uncertainty, never an inferred result; the original key recovers truth.

Read-only availability consults only confirmed appointments. Proposals are not reservations. The controlled concurrency demo independently reads committed rows before scoped cleanup; its final cleanup removes ephemeral fixture rows, not real business records. See [API/recovery](API_DESIGN.md) and [M3 evidence](evidence/M3_report.md).
