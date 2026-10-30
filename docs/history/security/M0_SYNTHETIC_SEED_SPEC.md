# M0 synthetic seed specification

This public copy retains the M0 artificial catalog provenance. The accepted implementation is app/db/seed.py; no legacy booking, clinic or insurance record is an input. This is documentation, not authorization to run a database seed during R1A.

## Provenance and catalog

All labels and identifiers below were chosen from scratch for this specification on 2026-10-13. No real person, clinic, address, phone number, clinical reason, or patient identifier is represented.

| Entity | Stable fixture UUID | Artificial label / code | Attributes |
| --- | --- | --- | --- |
| Clinic | `00000000-0000-4000-8000-000000000001` | `Synthetic Demo Clinic` | Timezone `America/Chicago`. |
| Practitioner | `00000000-0000-4000-8000-000000000101` | `Demo Clinician 01` | Active; belongs to the synthetic clinic. |
| Practitioner | `00000000-0000-4000-8000-000000000102` | `Demo Clinician 02` | Active; belongs to the synthetic clinic. |
| Appointment type | `00000000-0000-4000-8000-000000000201` | `follow_up` | Active; 30 minutes. |
| Appointment type | `00000000-0000-4000-8000-000000000202` | `initial_consultation` | Active; 60 minutes. |

Both practitioners have one weekly schedule per ISO weekday 1–5, opening at `09:00` and closing at `17:00`. This yields ten weekly schedule rows. Weekend rows are absent. No holidays/breaks, insurance, real clinic contacts or additional practitioners are seeded.

## Initial state and later test cases

The initial DB seed has zero appointments, proposals, sessions, turns, conversation items and idempotency records. Tests create isolated synthetic session-owned records themselves; they do not import historical patients or recordings.

The accepted tests use an explicit frozen aware clock for dated cases. Candidate examples are generated from the weekly schedules with 30-minute alignment and the approved 30/60-minute durations. Accepted M2/M3 rules use elapsed UTC hours with inclusive 24-hour notice and 90-day horizon, and cover expiry, DST, conflict and idempotency. R1A does not rerun those tests.

These UUIDs are fixture identifiers, not authentication tokens. Future seed code must be idempotent and run only against the explicitly selected local synthetic demo/test database, with no implicit reset of other databases.

## Legacy retirement marker

`data/appointments.json` is replaced with a valid JSON object containing empty appointment types, availability, bookings and scheduling rules, plus an explicit `RETIRED` marker. This file is not the new synthetic seed. It exists only to remove uncertain current-tree records without changing legacy application code or copying those records elsewhere. Its empty availability supplies no bookable legacy fixture slots.

The accepted runtime is independent of that file; retained static safety checks require the empty marker. Historical records remain outside this candidate. No legacy application is included or launched.
