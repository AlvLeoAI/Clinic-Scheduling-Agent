# ADR index — approved baseline and implementation

Source: [public product baseline](ARCHITECTURE_BASELINE.md), derived from approved engineering baseline 1.0. Internal execution instructions remain private. All eight decisions are implemented in the local prototype; this index does not add product policy.

| ADR | Decision | Implementation/evidence |
| --- | --- | --- |
| ADR-001 | Explicit CLI confirm action; no LLM authorization | `cli/client.py`, M3 confirmation and M6 lost-response/direct-route tests. |
| ADR-002 | 30/60-minute types, 24h notice, 90-day horizon, Chicago timezone | M2 policy/API and M3 confirmation revalidation tests. Bounds are inclusive elapsed UTC durations. |
| ADR-003 | Two practitioners, weekdays 09:00–17:00, 30-minute grid | Synthetic DB catalog/weekly schedules; M2 boundary/DST tests. |
| ADR-004 | Immutable ten-minute proposals; one pending/session; approved terminal states; no hold | M3 lifecycle/concurrency tests, M5 four-state replay, M6 terminal CLI display. |
| ADR-005 | FastAPI v1, eight functional operations plus health, three agent tools | Actual [OpenAPI snapshot](openapi.json), route-scope and schema tests. |
| ADR-006 | PostgreSQL sessions/conversation, bounded context, opaque bearer, serialization/recovery | M4 journal/lease/fence/dedup/restart tests. Session lifetime approved as 24h without sliding renewal. |
| ADR-007 | Responses store=false, strict/nonparallel, max five calls, Pydantic | Unchanged REST adapter over httpx, mocked transport tests; live support NOT RUN. |
| ADR-008 | Independent backend and agent evaluation; concurrency critical | M5 independent oracle/negative controls and M6 controlled real 23P01 demo. |

Accepted implementation choices: typed model reply plans with backend rendering, refreshed proposal state on completed chat replay and REST/httpx instead of the suggested SDK. See [M4/M5 review](M5_RECONCILIATION.md). M6 changes no booking protocol or agent permission boundary.
