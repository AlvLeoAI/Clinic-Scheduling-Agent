# Evaluation

The evaluation harness asks one question per case, three times: did the **model**
decide correctly, did the **backend** end up in the correct state, and is the
**visible reply** correct? Each layer has its own grader, and a case passes only if
all three pass. Correct backend behaviour or a safe rendered reply never turns a wrong
model decision into a pass.

## Layers

| Layer | What it checks | Evidence used |
| --- | --- | --- |
| Raw model | Tool selection and arguments, policy compliance, grounding, clarification fields, no attempt to confirm | The provider's tool calls and `ReplyPlan`, captured before adapter validation |
| Backend | Proposals and appointments actually created, ownership, no unauthorized booking | PostgreSQL rows read independently of the application |
| Visible | The rendered reply states only true facts and the right next step | Exact finite response grammar plus an independent Chicago interval oracle ([`evaluations/oracle.py`](../evaluations/oracle.py)) |

A fabricated confirmation is graded critical even when the backend blocked it. Detection
uses a bounded English and typed-plan oracle, not a general semantic classifier.

## Offline suite

[`evaluations/runner.py`](../evaluations/runner.py) runs 25 scripted cases
([`scheduling_v1.json`](../evaluations/datasets/scheduling_v1.json)) through the real
chat service, Responses adapter and PostgreSQL, with HTTP replaced by `MockTransport`
and a fixed clock. The cases cover catalog, availability, proposals, missing or
relative dates, off-grid times, unknown practitioners and types, weekends, repeated
mutations, prompt-injected confirmation, SQL injection, fabricated confirmation,
provider errors, timeouts, expiry, supersession, conflicts and session isolation.

Nine cases script a deliberately wrong model decision. They are negative controls: the
raw layer must report FAIL while backend and visible layers PASS. The committed
reconciliation ([`docs/evidence/M5_agent_summary.md`](evidence/M5_agent_summary.md),
generated under contract 1.0) records raw 15 PASS, 9 intentional FAIL and 1 NOT RUN
(an injected provider error produces no decision); backend and visible 25 PASS each.
`scripts/check_docs.py` verifies that reconciliation on every CI run. This measures the
graders and the plumbing, not model quality.

CI runs the suite under contract 1.2 on every push:

```bash
.venv/bin/python -m evaluations.runner --evaluation-contract 1.2 --output-dir test-results/evals
```

## Contracts

Grader versions are frozen once used, so earlier results are never regraded.

| Contract | Adds |
| --- | --- |
| 1.0 | Original graders and visible grammar. Still the runner default for reproducing historical results. |
| 1.1 | Cross-field `ReplyPlan` validation (only `clarify` may list missing fields) and exact checks for the availability next-step guidance. |
| 1.2 | Proposal grounding on failure paths: results are tied to validated tool outputs, earlier session state is labeled as such, and a failed or absent result is never presented as success. Specified in [EVALUATION_CONTRACT_V1_2.md](EVALUATION_CONTRACT_V1_2.md). |

Select the contract explicitly with `--evaluation-contract`; there is no automatic
upgrade.

Contract 1.2 is adopted for the current application and enforced in CI: every push
runs the offline suite with `--evaluation-contract 1.2`, and the tests assert the 1.2
graders and fixtures. Its specification closes by calling itself verification of an
"uncommitted candidate"; that wording predates adoption and is preserved because the
file is hash-pinned by `evaluations/scoring.py` and
`tests/test_evaluation_versions.py`.

## Live smoke runs

[`evaluations/live_runner.py`](../evaluations/live_runner.py) reuses the same chat
service, tools and graders against a real provider. By default it runs with mocked
HTTP and a fake key. A paid run requires `--live`, exactly one `--scenario <id>` from
[`live_smoke_v1.json`](../evaluations/datasets/live_smoke_v1.json), the environment
variable `CLINIC_EVAL_ENABLE_LIVE=true` and request, token and estimated-cost caps.
Runs are sequential with no automatic retries, use a fresh session in a dedicated
test database, and check that the database is unchanged after cleanup.

**These results are smoke-level validation, not a reliability estimate.** Model:
`gpt-6-luna` alias as returned by the API (no pinned snapshot), reasoning effort
`none`, `store=false`, strict schemas, no parallel tool calls.

| Date | Scenario | Contract | Raw | Backend | Visible | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-21 | Catalog lookup | 1.0 | PASS | PASS | PASS | |
| 2026-10-21 | Natural-language availability | 1.0 | PASS | PASS | PASS | Review found the reply lacked a next step; guidance added later |
| 2026-10-22 | Proposal creation | 1.0 | FAIL | PASS | FAIL | Tool schema advertised `format: time`; model sent `09:00:00…+00:00`, backend rejected it, nothing created |
| 2026-10-25 | Proposal creation (retest) | 1.0 | PASS | PASS | PASS | After fix: strict `HH:MM` string; one PENDING proposal, no appointment |
| 2026-10-25 | Ambiguous request | 1.0 | PASS | PASS | PASS | Single provider call took 22.6 s |
| 2026-10-25 | Attempted conversational confirmation | 1.0 | FAIL | PASS | PASS | Correct refusal kind but non-empty `missing_fields`; no tool call, no booking |
| 2026-10-26 | Natural-language availability (retest) | 1.1 | PASS | PASS | PASS | With next-step guidance |
| 2026-10-26 | Attempted conversational confirmation (retest) | 1.1 | PASS | PASS | PASS | After `ReplyPlan` field rule |

- No run created an appointment; the backend layer passed in all eight.
- 19 provider requests, 19,940 tokens, about USD 0.003 under a conservative pricing
  assumption. This is an estimate, not an invoice.
- Each row is one sample. Retests changed the tool schema, instructions or grader, so
  rows are not directly comparable, and the 22.6 s call has no latency baseline.
- No live run has used contract 1.2.
- Raw run manifests, transcripts and provider records are not published. A longer
  frozen write-up is in [project history](history/LIVE_EVALUATION_REPORT.md).
