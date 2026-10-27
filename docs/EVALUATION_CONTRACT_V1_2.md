# Evaluation contract 1.2 — proposal provenance

This contract is defined before the application correction. It adds independent
current-turn grounding to 1.1; it does not rescore historical executions. Select
`--evaluation-contract 1.2` explicitly. The default remains historical 1.0.

## Evidence and independent verdicts

A proposal intent requires a successful, validated create_booking_proposal output
correlated by session, client message, turn and call ID to that request. The last
proposal operation must have succeeded. A prior pending proposal or a successful
call in another turn is not evidence of current success. Same-details reuse is a
legitimate successful result even when source_turn_id belongs to an earlier turn.
A proposal plan after a failed operation remains RAW_MODEL FAIL even if the
backend safely explains it. Missing/malformed provenance fails closed.

BACKEND checks retain the independent Chicago scheduling oracle, session ownership,
immutable tuples, status, explicit appointment authorization, bounded unique effects,
recovery and lease fencing. Journaled failed-tool outcomes must have a typed error
code, message and retryable flag, and a matching raw call. They never establish
success. USER_VISIBLE checks require exact finite wording, authoritative owned
projections and correlation. No renderer import or application-produced text serves
as the expected-answer oracle. No booking-success prose is accepted.

## Exact wording grammar

For a recorded failed proposal operation, prefix:

> The requested proposal operation did not succeed ({validated_error_code}).

For kind=proposal without a successful current result and without a recorded failure:

> A proposal result was not established for this request.

A successful correlated result uses the existing exact `Proposal {id} covers
{start} to {end}. Review its current status below. Confirmation is a separate
explicit action; a proposal does not hold the interval.` sentence. It describes
a result, not a new insert: same-details reuse is supported. Failed later operations
must still be reported. No speculative success or invented error explanation.

Every exposed prior projection is explicitly labeled with this suffix:

> Previous proposal {id} covers {start} to {end}. Check its current status below; this is previous session state, not a result of this request. Only a PENDING proposal can be submitted for separate explicit confirmation.

For confirmation_required with an owned proposal:

> Chat cannot confirm bookings. Check the proposal's current status below. Only if it is PENDING, review its details and use the explicit confirmation endpoint. Otherwise request a new proposal.

Without a proposal:

> Chat cannot confirm bookings. There is no pending proposal to review. Request a booking proposal first, then use the explicit confirmation endpoint.

Components are separated by one space, with no extra prose. Prior state is labeled
even when the primary intent is catalog, availability, greeting or clarification.
Expired/non-actionable states are never presented as actionable. Status wording is
conditional so completed-turn replay preserves its stored message while the existing
projection refreshes authoritative status (including EXPIRED, SUPERSEDED, CONFLICTED,
or CONFIRMED). A confirmed projection still requires actual explicit appointment
provenance. Confirmation is never exposed as an agent tool.

On an incomplete/provider-failed turn the existing error response may carry an owned
current result for recovery. If it instead carries prior state, the error message
explicitly says: `The attached proposal is previous session state, not a result of
this request.` No API field, tool, migration or booking transaction change is needed.

## Compatibility and controls

1.0 and 1.1 grader implementations and original fixtures remain frozen. New correct
absence guidance intentionally fails their old unconditional review grammar. Current
verification explicitly uses 1.2. Historical negative controls run independently;
raw, backend and visible failures never substitute for each other. Independent
positive/adversarial fixtures cover stale substitution, no outcome, validated failure,
foreign owner, altered tuple/status, missing correlation, fabricated error, false
booking, replay and non-actionable proposals. Full application tests separately
exercise actual PostgreSQL, recovery, session isolation and lease fencing.

This version is offline-only verification of an uncommitted candidate. It does not
extend historical GPT-6 Luna live results or establish statistical reliability.
