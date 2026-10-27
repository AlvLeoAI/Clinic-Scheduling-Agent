# R2C.1 offline quality candidate

R2C.1b adds [explicit evaluation contracts 1.0 and 1.1](EVALUATION_CONTRACTS.md).
The frozen-grammar incompatibility described below applies to 1.0. Select 1.1
explicitly for this application's new guidance and semantic contract; historical
results and the requirement for separate paid-evaluation authorization remain unchanged.

Candidate configuration **r2c.1-offline-quality-1.0.0** changes the application instructions,
reply-schema descriptions, application semantic validation and deterministic availability wording.
The three tools, including the repaired exact `HH:MM` proposal input, remain unchanged.
Dataset version labels describe the frozen fixtures; they do not identify this candidate's prompt.
Record source, instructions, reply-schema, tool-schema and grader hashes with any future experiment.

Only `kind=clarify` may have nonempty `missing_fields`, and those fields should identify genuinely
missing or ambiguous scheduling details. Every other kind, including `confirmation_required`,
requires `[]`. The strict wire schema remains a required-field object with enum/array properties;
it deliberately has no conditional JSON Schema keywords or root union. Descriptions and instructions
express the semantic rule, and Pydantic validates it locally. A syntactically valid provider response
can therefore still be semantically invalid.

Invalid combinations are rejected, never normalized. They follow the existing 503
`SERVICE_UNAVAILABLE` path: the turn is FAILED, no successful reply result is stored and the API
does not assert conversation or booking success. Provider HTTP completion is distinct from reply
acceptance. An already committed owned proposal remains recoverable as PENDING; rejection does not
undo or repeat that effect. The existing same-message retry protocol remains available, with no
automatic provider retry. Evaluation wrappers capture the raw decision before validation, so a
rejected model plan remains a raw failure. Operational logs do not include model text or metadata.

For nonempty, freshly checked PostgreSQL intervals, the renderer now invites selection of a returned
interval to request a proposal and explains that booking requires separate explicit confirmation.
It still says these are not reservations and instructs users to refresh availability. It neither
creates proposals nor confirms appointments. Empty/exhausted checks retain their no-interval reply.
Completed message replay remains a historical check, not a new availability query or reservation;
clients should query again and proposal/confirmation operations revalidate availability.

## Frozen evaluation boundary

Historical M5 and R2B datasets, graders, prompts, reports and verdicts are preserved. Original S3,
its retest, and S5 remain separate historical experiments. No historical case is rescored here.
The frozen v1 visible grader accepts an exact availability sentence grammar. It rejects the new
guidance even when interval facts are correct. Running that grader on this candidate is expected
to expose the incompatibility, not establish a passing candidate benchmark. Do not strip the
guidance, relax the old grader or describe backend safety as raw-model success to obtain green results.

New deterministic tests independently check interval grounding, selection/proposal/confirmation
boundaries, changing availability, absence of rendering side effects and rejected raw metadata
through the actual mocked Responses adapter. They test application behavior, not model reliability.
R2C.1b supplied the separately reviewed 1.1 grader and passed 616 local regression tests, preserving the explicit old-grammar incompatibility. R2C.2 then observed one successful S2 and one successful S5 live regression under 1.1. These runs do not overwrite original failures or establish reliability; see the [evaluation report](LIVE_EVALUATION_REPORT.md). Further paid runs require separate owner authorization, fresh fingerprints, isolated synthetic PostgreSQL and reviewed budgets. PERF-001 and unrelated failed-tool reply handling remain open.
