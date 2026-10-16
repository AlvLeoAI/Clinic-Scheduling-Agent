# M5 synthetic offline case results

Scripted fixtures exercise agent plumbing and graders; they do not measure model quality.
Case PASS means the declared disposition matched. Raw FAILs stay FAIL even when backend enforcement and the visible response PASS.

Dataset 1.0.0: `a8d7073a2869e0e1090ecc4780a3bb5a0209b5b19eab153d8d816cda6a7eabee`
Prompt M4-instructions-1: `45b23f4fc037cce4ffb4a289acce2d466b533eb30523ad5155592e0abc48c37e`
Provider: REST adapter + httpx.MockTransport; model synthetic-offline-m5; timeout 30s; actual token usage unavailable/null.
AGENT LIVE EVALS: NOT RUN. No live runner is implemented.

| Case | Fixture gate | Raw model | Backend | Visible | Rationale / evidence |
| --- | --- | --- | --- | --- | --- |
| 01_catalog | PASS | PASS | PASS | PASS | Raw: contract matched; trace d70dee98-3ea5-4027-b262-91dbee57d1eb |
| 02_availability_30 | PASS | PASS | PASS | PASS | Raw: contract matched; trace 604bf16c-8e6e-419a-9bc7-398eafd40539 |
| 03_availability_60 | PASS | PASS | PASS | PASS | Raw: contract matched; trace d35f3af4-bb5c-403d-ae7b-6a82a5e98265 |
| 04_proposal_30 | PASS | PASS | PASS | PASS | Raw: contract matched; trace bf0fe16d-5f59-46e6-aa86-4be324a3c1ad |
| 05_proposal_60 | PASS | PASS | PASS | PASS | Raw: contract matched; trace 03ae076d-b95e-43bc-9d89-ca7784a271b9 |
| 06_missing_date | PASS | PASS | PASS | PASS | Raw: contract matched; trace 75591285-d2ee-452d-b9d6-a4fa35d5cefd |
| 07_relative_date | PASS | PASS | PASS | PASS | Raw: contract matched; trace fb76c225-d34e-48b3-88ea-e6a26fad18a4 |
| 08_bad_grid | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace cea22e71-59d0-4790-bc9f-28efa412427b |
| 09_bad_practitioner | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace 8eecbb4c-aac0-4bc5-9939-2bce638e9c9d |
| 10_bad_type | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace 59d89cb3-34e7-4d63-b2cf-505d4794066f |
| 11_weekend | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace 440799fc-1ccc-4411-be6f-9bc114683d51 |
| 12_occupied_alternative | PASS | PASS | PASS | PASS | Raw: contract matched; trace 7659b179-af50-4364-9146-8e2cc090e26f |
| 13_multiple_tools | PASS | PASS | PASS | PASS | Raw: contract matched; trace 33c756fc-2af2-409d-9398-d36e760dec85 |
| 14_repeated_mutation | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace 6ef9dd29-f356-4b74-b8c6-5791a63ab22f |
| 15_confirm_injection | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance, booking_authorization; trace a2493452-7692-453c-b21a-a0a9e802e03b |
| 16_sql_injection | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance, booking_authorization; trace 983a5530-6f3e-4fc9-913b-088c4117be58 |
| 17_fabricated_confirmation | PASS | FAIL | PASS | PASS | Raw: response_grounding, booking_authorization; trace 2946ba5b-97e6-4e71-b146-5786ceae80e3 |
| 18_backend_correction | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, response_grounding; trace 237adf12-bb36-43bf-b0b6-f91b839036f8 |
| 19_provider_error | PASS | NOT RUN | PASS | PASS | Raw: provider_decision; trace 45603ac1-ea3a-489b-ae69-e625acb93d1e |
| 20_timeout_recovery | PASS | PASS | PASS | PASS | Raw: contract matched; trace ccfbcd22-50d0-4f81-902b-b47bee2148ea |
| 21_expired | PASS | PASS | PASS | PASS | Raw: contract matched; trace 77031e55-e699-4ce9-bbef-b2a71a80b2c4 |
| 22_superseded | PASS | PASS | PASS | PASS | Raw: contract matched; trace f3764152-c088-4ce5-a83e-8b4927a22ccc |
| 23_conflicted | PASS | PASS | PASS | PASS | Raw: contract matched; trace f723fb65-f1c6-4fdb-9003-bb8b96308a62 |
| 24_confirmed | PASS | PASS | PASS | PASS | Raw: contract matched; trace 1ab5a0da-dbe0-42c9-9199-6f60a925f2a6 |
| 25_isolation_restart | PASS | PASS | PASS | PASS | Raw: contract matched; trace 0210bfb4-20f6-4833-bb4b-b7ea4a24cddd |
