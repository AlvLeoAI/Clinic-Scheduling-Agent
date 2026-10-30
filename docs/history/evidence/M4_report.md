# M4 — Persistent bounded agent orchestration — historical public extract

> Superseded on 2026-10-30: see README [Security history](../../../README.md#security-history).

Public-safe extract prepared during R1A on 2026-10-16. Original private report and exact ledgers remain unchanged outside this candidate. Results below were recorded in the original milestone; they were not rerun from this candidate. Owner has accepted M0–M6 local technical gates. Public release remains BLOCKED by unresolved historical privacy/security and separate verification/authorization gates.

Recorded final suite: 293 passed, 0 failed, 0 skipped, one inherited warning; 59 M4 cases extended the prior 234. Three strict tools, durable conversation journal, lease/fence/session serialization, client-message deduplication, bounded whole context and restart recovery were exercised with fake transports.

Accepted choices: typed reply plans with deterministic backend rendering; current proposal status projection on completed chat replay while retaining historical turn identity; and an httpx REST Responses adapter with injectable transport. Confirmation remains direct and outside model tools; M3 durable replay/transaction semantics remain intact.

Limits: 24,000 characters rather than tokenizer accounting, per-phase timeout rather than absolute deadline, response-size checking after buffering, same-session recovery before bearer expiry, no retention/purge policy. Model-specific live compatibility, semantic reliability, load and broad process-crash behavior remain NOT RUN. See [M5 review](../M5_ARCHITECTURE_REVIEW.md) and [agent boundaries](../AGENT_EVALUATION.md).
