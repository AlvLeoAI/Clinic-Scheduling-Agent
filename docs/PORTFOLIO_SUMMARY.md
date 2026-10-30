# Clinic Scheduling Agent — portfolio summary

A synthetic scheduling prototype that combines a language model with deterministic booking guarantees. FastAPI and Pydantic validate requests; PostgreSQL is the authority for availability and reservations. The agent can consult the catalog, check availability and create a proposal. Only an authenticated client's separate confirmation action can reserve an appointment.

Scheduling enforces Chicago business hours, a thirty-minute grid, thirty/sixty-minute appointment types, notice and horizon bounds. Immutable proposals expire after ten minutes. Atomic confirmation revalidates policy and uses PostgreSQL exclusion constraints to prevent practitioner overlap. Durable idempotency returns the committed result after a lost HTTP response, without inferring success from a timeout.

Persistent conversations use correlated tool outputs, short session leases and write fences. Strict tool contracts and semantic ReplyPlan validation constrain interpretation, while deterministic rendering uses authoritative backend facts. Tests and independent graders separate model choices, backend safety and user-visible correctness, including negative controls that intentionally inject errors.

Real GPT-6 Luna smoke evaluations exposed a time-schema mismatch and incorrect confirmation metadata. Narrow, versioned repairs and separately authorized retests demonstrated the intended behavior in individual samples. Original failures remain visible. Hosted CI passed 378 tests at root `6521b87`, 616 at `9b0c0df`, and 682 at committed `e1b572f` with explicit v1.2. Independent local and remote fresh clones of the latest commit also passed 682 tests each. No live model evaluation has used v1.2; see [testing](../TESTING.md) and [current status](CURRENT_STATUS.md).

## Architecture overview

Client → FastAPI → chat orchestration → Responses adapter → three validated tools → deterministic services → PostgreSQL. Explicit client confirmation takes a separate API path directly to the atomic Booking Service. The model has no confirmation tool. See the [architecture diagram](../SYSTEM_DESIGN.md).

## Reproducible concurrency demonstration

Prepare an independently isolated synthetic test runtime following [testing](../TESTING.md) and [operations](OPERATIONS.md), then run sequentially:

```bash
.venv/bin/python scripts/demo_concurrency.py --synthetic-only --evidence test-results/portfolio/concurrency.json
```

The script coordinates two independent clients/connections attempting overlapping reservations for the same practitioner. Verify exactly one committed reservation and one conflict from authoritative database evidence; do not treat a timeout as success. It refuses a nonempty appointment table and cleans only its own fixture rows. Run only on disposable synthetic data; this command was not executed during the documentation freeze. The scripted CLI separately demonstrates committed-response-loss recovery with the same idempotency key.

**Maturity:** local demonstration prototype, repository private. Historical credential/audio/privacy remains an unresolved P0 public-release blocker. No production readiness, EHR integration, regulatory compliance or statistical model-reliability claim. See [live results and limitations](LIVE_EVALUATION_REPORT.md) and [release gates](RELEASE_READINESS.md).
