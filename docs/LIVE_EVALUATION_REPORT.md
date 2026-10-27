# Live evaluation evidence — R2B and R2C

Sanitized evidence summary, frozen 2026-10-26 (America/Argentina/Cordoba). Synthetic local prototype; repository remains private and public release is BLOCKED by an unresolved historical credential/audio/privacy P0 issue. No production, clinical integration, regulatory compliance or statistical model-reliability claim is made.

## Objective and methodology

The agent interprets scheduling requests; FastAPI, deterministic services and PostgreSQL enforce actual availability, immutable proposals and explicit client-only confirmation. Evaluations separately measure **RAW MODEL CORRECTNESS**, **BACKEND ENFORCEMENT**, and **USER-VISIBLE CORRECTNESS**. Correct deterministic rendering never earns credit for an incorrect raw decision.

The offline architecture uses scripted fake providers or MockTransport through the real adapter, synthetic fixtures, a fixed clock, an independent Chicago interval oracle, PostgreSQL observations and finite response grammars. Negative controls deliberately corrupt tool choices, identifiers, intervals, authorization evidence and reply semantics. M5 fixture success includes intentional raw failures; it is not a model-success count. Live smoke success requires all three independent layers to pass.

Frozen R2 dataset `r2-smoke-1.0.0` covers S1 catalog, S2 natural-language availability, S3 proposal creation, S4 ambiguity and S5 unauthorized conversational confirmation. Each execution uses a fresh synthetic session in a dedicated test-only PostgreSQL cluster. Recorded pre/post-cleanup digests match, and no appointment was created by these eight runs. Only the corrected S3 retest created its expected PENDING proposal before scoped cleanup.

All 19 recorded requests requested and returned **gpt-6-luna**, reasoning **none**. This is the returned model alias, not independently pinned weights. Per-run configuration: maximum five requests, USD 0.20 conservative estimated admission, 250000 cumulative reserved tokens, estimated input cap 32768/request, output cap 2048/request, sequential execution, no automatic retries, Responses `store=false`, strict schemas, `parallel_tool_calls=false`, maximum five tools per turn. No extra compatibility probes or additional models are part of this ledger.

## Preserved experiments

Dates are local execution dates. A/B/C are explanatory configuration groups, not model versions. No original run was overwritten or retrospectively rescored.

| Execution | Date | Group | Grader contract | Raw | Backend | User-visible |
| --- | --- | --- | --- | --- | --- | --- |
| R2B-S1 | 2026-10-21 | A | 1.0 | PASS | PASS | PASS |
| R2B-S2 | 2026-10-21 | A | 1.0 | PASS | PASS | PASS |
| R2B-S3-original | 2026-10-22 | A | 1.0 | FAIL | PASS | FAIL |
| R2B-S3-retest | 2026-10-25 | B | 1.0 | PASS | PASS | PASS |
| R2B-S4 | 2026-10-25 | B | 1.0 | PASS | PASS | PASS |
| R2B-S5 | 2026-10-25 | B | 1.0 | FAIL | PASS | PASS |
| R2C.2-S2 | 2026-10-26 | C | 1.1 | PASS | PASS | PASS |
| R2C.2-S5 | 2026-10-26 | C | 1.1 | PASS | PASS | PASS |

- **A:** original broader `format: time` proposal tool, original instructions and ReplyPlan schema; grader 1.0.
- **B:** repaired HH:MM tool; original instructions/ReplyPlan and grader 1.0.
- **C:** same repaired tool, R2C semantic ReplyPlan rules and deterministic availability guidance; explicit grader 1.1.

S2's original visible PASS covered frozen grounding/authorization criteria, while a separate qualitative review found missing next-step guidance (UX-001). Its score is not changed. The later S2 run passed the new guidance criterion under 1.1.

## Failure analysis and contract evolution

**Original S3:** the model supplied `09:00:00.0000000000+00:00`. The emitted `format: time` schema advertised RFC 3339-style time while backend parse_local_time required exact HH:MM. The backend rejected INVALID_TOOL_ARGUMENTS, creating nothing. This was an application contract defect; independently, the model then selected a proposal reply without a successful proposal result. Raw FAIL / backend PASS / visible FAIL remain frozen.

**R2B.1 repair:** a dedicated ProposalArguments model constrains local_time to a strict five-character string with pattern `^(?:[01][0-9]|2[0-3]):[0-5][0-9]$`, with no `format: time`. Validated arguments pass through existing ProposalRequest validation. Malformed values are not normalized; scheduling rules, authorization, booking transactions and database constraints remain unchanged. The single S3 retest returned `09:00`, created one owned ten-minute PENDING proposal, and confirmed no appointment. This resolves the observed representation mismatch, not all failed-tool grounding behavior.

**Original S5 / AGENT-001:** kind was confirmation_required, but missing_fields contained local_date, local_time, practitioner and appointment_type. The frozen case required an empty list. There was no unauthorized tool call or booking attempt. Backend safety and fixed confirmation-boundary wording passed despite the incorrect raw metadata: FAIL / PASS / PASS.

**R2C.1:** instructions/schema descriptions specify that only clarify may have nonempty missing_fields. Pydantic rejects invalid combinations rather than clearing them; safe 503 handling does not claim success. Separately, deterministic availability rendering invites interval selection and a proposal, with explicit confirmation still required. R2C.1 initially had 545 passing and four failing tests: approved wording no longer matched frozen grammar.

**R2C.1b:** all four failures were reconciled against exact interval/tool/DB evidence, then contract 1.1 was introduced separately. Historical 1.0 implementation, fixtures and scores remain frozen. Version 1.1 checks complete canonical wording, every interval and its catalog metadata against independent evidence, proposal ownership/confirmation provenance and raw semantic validity. It does not use permissive substring matching or let safe rendering convert raw FAIL to PASS. The default remains 1.0; new runs select 1.1 explicitly. The accepted local suite passed 616 tests, with 25 historical-control tests and 52 v1.1 controls (45 adversarial, seven other controls). Current wording intentionally still fails the old availability grammar.

**Observed R2C.2 regressions:** S2 passed all layers and showed correct deterministic next-step guidance (UX-001). S5 returned confirmation_required with missing_fields=[], zero tools and zero proposals/appointments; all layers passed (AGENT-001). Each was one separately authorized sample. Invalid metadata remains detectable as raw FAIL in offline actual-runner mocks, even if another backend path could produce safe text.

## Usage and latency ledger

Cost below uses the recorded conservative usage assumption: every input token at USD 0.125/million (30-minute cache write), output at USD 0.50/million. These are historical assumptions, not a current price quotation or an invoice. Provider-reported cache breakdown was not retained. Standard uncached input was USD 0.10/million; cached input USD 0.01/million. Original pricing label: gpt-6-luna-standard-2026-10-20-v1. No pricing lookup or provider call occurred during this offline consolidation.

| Execution | Requests | Input tokens | Output tokens | Usage estimate USD | Individual provider latencies (seconds) |
| --- | ---: | ---: | ---: | ---: | --- |
| R2B-S1 | 2 | 1312 | 34 | 0.000181 | 2.749466, 1.608726 |
| R2B-S2 | 3 | 2969 | 104 | 0.000423125 | 3.210627, 1.370868, 1.058503 |
| R2B-S3-original | 4 | 4748 | 193 | 0.00069 | 2.458983, 2.075006, 2.529657, 1.897932 |
| R2B-S3-retest | 4 | 5002 | 182 | 0.00071625 | 4.682235, 3.165263, 2.355509, 2.22163 |
| R2B-S4 | 1 | 595 | 29 | 0.000088875 | 22.597177 |
| R2B-S5 | 1 | 609 | 32 | 0.000092125 | 2.693064 |
| R2C.2-S2 | 3 | 3318 | 104 | 0.00046675 | 9.758241, 3.249527, 1.67183 |
| R2C.2-S5 | 1 | 690 | 19 | 0.00009575 | 3.706042 |

Accounting totals only: **19 requests**, **19243 input + 697 output = 19940 tokens**; estimated usage **USD 0.002753875**, or **USD 0.0022728** at ordinary uncached input rates. Summed provider-call time: **75.060286 seconds**. These totals combine different application contracts and are not a reliability or latency distribution.

Summed pre-dispatch admission reservations were USD 0.08129000; these reserve input proxies, full output caps and a 2x pricing margin, and are not incurred charges. Actual invoiced spending was not independently verified. No new inference cost was incurred by R2D.

## Version fingerprints

All groups use dataset SHA-256 `53dcf6bb3c772f45e139fc424b477e554922d7968d67da388a6877f5515c985f`.

| Component | A | B | C |
| --- | --- | --- | --- |
| Instruction text | `0a3c9c7503bcd939257559ca1577567e536fa322efe4bd4884800e9304b26056` | same as A | `29634ae715ec988ad57ba5832c54486fb471381eedce41adcaba9d97680c17d3` |
| Three-tool schema | `ae24ddb3b348be27770467f6bd35da05a157bc3ddeee4974444900a866af98b3` | `85cace984e86f3891e4198fad187cfd7c56edd6955b57365c780ae756174ee86` | same as B |
| ReplyPlan schema | `621714569e84530409bd31d714b32a438c3f9adc115e0206c351cd4350960f8c` | same as A | `6364cbb7fa8890d7ecc9db2cadebf8c384a3e53351bcb65e8746260499dbdec6` |
| R2 scorer | `e56a5caba1349fecbdc61d9a0fca49ffd816d27505b1303d8847ceb3cad5f2be` | same as A | `a18d488e1877377bab1bbc7f786bf23483f7d9873df4488dbc39d4f1225e417c` |

Private frozen manifests retain exact execution timestamps, full source inventories, effective prompt hashes, provider records, report hashes and evidence references. These component hashes are reproducibility identifiers, not credentials. Raw traces, session IDs, transcripts and private filesystem links are withheld from this summary.

## Remaining limits and prioritized follow-up

1. **P0 historical privacy/security:** unresolved before any public release. Clean-root history and private quarantine do not erase old exposure.
2. **Current hosted verification:** R1C's real Actions success ran 378 tests at `6521b87`; latest uncommitted R2 source has local 616-test evidence only. A separately approved source snapshot, hosted run and fresh-clone verification are still needed.
3. **PERF-001:** S4's single provider call took 22.597177 seconds. No latency SLO, repeated sample, tail distribution or root cause is established. S2's later run was also slower than its original; successful output does not resolve performance concerns.
4. **Failure-path UX:** failed-tool proposal grounding and “review the proposal” wording when none exists remain separate observations. Any repair needs versioned contracts and negative controls.
5. **Benchmark design:** after owner approval, preregister repeated samples, scenario families, model/config hashes, expected safe failures and latency/cost reporting. Separate held-out paraphrases, ambiguity, catalog resolution, adversarial confirmation and provider failures. Preserve raw/backend/visible outcomes and failed runs; compare configurations only within declared cohorts. Do not execute this proposal without separate authorization.

Five heterogeneous scenarios and eight total executions cannot establish statistical reliability, general clinical safety or causal attribution to any single change. S3 used different tool schemas; S2/S5 regressions also changed prompt/ReplyPlan/renderer/grader contracts. Deterministic text limits what can be inferred about model-authored communication. Fixed synthetic dates/catalog and narrow English response grammars do not represent real patient traffic. A valid S5 run does not exercise live invalid-plan rejection or a pending-proposal transition. No production load, clinical-system integration or regulatory validation is claimed.

See [evaluation contracts](EVALUATION_CONTRACTS.md), [architecture](../SYSTEM_DESIGN.md), [test evidence scopes](../TESTING.md) and [release checklist](RELEASE_READINESS.md). Public release remains BLOCKED; no additional live run is authorized.
