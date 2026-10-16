# M5 review of accepted M4 choices — public technical extract

Original review was recorded on 2026-10-15 before M5 implementation. This retrospective R1A public copy omits internal milestone execution instructions. The complete private original remains unchanged. No critical contradiction was found in the inspected fake-provider architecture; no application source change was justified. This does not establish live-model compatibility or quality.

## Typed reply plans

ChatService._final_plan validates the model's typed plan; app/agent/replies.py renders deterministic facts, rereads catalog/availability and obtains authoritative proposal state. Correct visible output may hide a wrong or absent model tool selection. M5 grades raw attempted calls/plans separately from deterministic enforcement and user-visible results. Case 18 deliberately omits the required catalog call: raw tool-selection/grounding FAIL remains FAIL while backend/visible layers PASS.

## Proposal status on completed replay

Stored turn/message/trace remain stable while the current proposal projection can become EXPIRED, SUPERSEDED, CONFLICTED or CONFIRMED. Cases 21–24 preserve immutable identity/tuple and verify unchanged provider/tool counts on replay. Conflict and booking come only from explicit direct confirmation outside chat; CONFIRMED requires an actual appointment. Whole chat JSON may differ; exact M3 confirmation replay is unchanged.

## REST adapter and measurement limits

Pinned httpx implements the accepted Responses wire contract with injectable transport: store=false, strict function schemas, nonparallel calls, matching call_id outputs, complete reasoning/manual context and a bounded tool loop. All 25 recorded offline scenarios traverse this unchanged adapter using MockTransport, alongside 11 dedicated wire/error/timeout tests and retained M4 protocol checks. Recorded prompt-package hashes match observed request metadata. Function-call fixtures use wire fields only, without evaluator diagnostic identity in model context.

Actual model-specific compatibility, schema/refusal behavior and semantic reliability are NOT RUN. Response-size checking occurs after buffering and timeout is per phase, not an absolute wall-time deadline. No SDK replacement, agent permission change or booking-protocol change was made. Historical Git privacy/security remains a separate P0 release blocker.

Original final M5 regression recorded 353 passes and a 25-case fixture gate. Raw remains 15 PASS / 9 intentional FAIL / 1 NOT RUN, separate from backend/visible 25 PASS each. Critical provider failure had no raw decision but safe backend/visible behavior actually ran. See [reconciliation](M5_RECONCILIATION.md), [public M5 report](evidence/M5_report.md) and [synthetic provenance](evidence/SYNTHETIC_PROVENANCE.md). No R1A runtime rerun is claimed.
