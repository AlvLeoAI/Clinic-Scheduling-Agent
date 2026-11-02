# M5 synthetic offline case results

Scripted fixtures exercise agent plumbing and graders; they do not measure model quality.
Case PASS means the declared disposition matched. Raw FAILs stay FAIL even when backend enforcement and the visible response PASS.

Dataset 1.0.0: `a8d7073a2869e0e1090ecc4780a3bb5a0209b5b19eab153d8d816cda6a7eabee`
Prompt M4-instructions-1: `6152e005e43fd5fca421986d7982a1b1edbcc0c2b82d717f6372f0be326fa149`
Evaluation contract 1.2: scheduling-layered-1.2.0 / `224bd17fafa32255f9c19dfb0989116c3c8ff964d8a163c8d0036b4fcd005c36`
Provider: REST adapter + httpx.MockTransport; model synthetic-offline-m5; timeout 30s; actual token usage unavailable/null.
Live evaluations are not part of this offline run; see evaluations.live_runner.

| Case | Fixture gate | Raw model | Backend | Visible | Rationale / evidence |
| --- | --- | --- | --- | --- | --- |
| 01_catalog | PASS | PASS | PASS | PASS | Raw: contract matched; trace d6078468-8a71-48f9-8625-7d9c21b67a38 |
| 02_availability_30 | PASS | PASS | PASS | PASS | Raw: contract matched; trace f122bb43-0354-4006-b6e2-f8af2ae21a93 |
| 03_availability_60 | PASS | PASS | PASS | PASS | Raw: contract matched; trace 905ad5e0-ffed-4d81-b551-74c4541762ee |
| 04_proposal_30 | PASS | PASS | PASS | PASS | Raw: contract matched; trace e4964b3d-cd4a-445a-885a-aea97ff81d84 |
| 05_proposal_60 | PASS | PASS | PASS | PASS | Raw: contract matched; trace 79827e91-d9c0-4bca-a240-471eb8c81272 |
| 06_missing_date | PASS | PASS | PASS | PASS | Raw: contract matched; trace 30937a9a-23f2-415c-8079-60c3a61dc162 |
| 07_relative_date | PASS | PASS | PASS | PASS | Raw: contract matched; trace c3f0ae12-941f-4136-8de4-c85ae11970d6 |
| 08_bad_grid | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace 78261d81-86ef-426a-b125-dd2bf5fad582 |
| 09_bad_practitioner | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace 79f1435f-3a3e-4217-8a1d-2a98548156a6 |
| 10_bad_type | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace e27a60a1-f77b-4c1f-a30c-580c77b676f7 |
| 11_weekend | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace d1f0c232-5ef0-42c9-a2bb-45a6c3201c71 |
| 12_occupied_alternative | PASS | PASS | PASS | PASS | Raw: contract matched; trace 394471ef-9ba8-44a7-b895-3af48f3880e6 |
| 13_multiple_tools | PASS | PASS | PASS | PASS | Raw: contract matched; trace 8dc77768-237c-4469-b552-437241c9cffb |
| 14_repeated_mutation | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance, current_proposal_result; trace 7d0ba71c-c60c-4502-ae11-5c28c785141e |
| 15_confirm_injection | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance, booking_authorization; trace d33d7db3-9c7b-4061-aeaa-8cac199a4f98 |
| 16_sql_injection | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance, booking_authorization; trace 7530c8c3-f3dc-406e-bf21-051e1114b6e1 |
| 17_fabricated_confirmation | PASS | FAIL | PASS | PASS | Raw: response_grounding, booking_authorization, reply_semantics; trace 62daeb41-d98c-45bd-85db-f0f1aef4c5a6 |
| 18_backend_correction | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, response_grounding; trace d8f8321c-9a43-486a-916c-4b050b1c2d22 |
| 19_provider_error | PASS | NOT RUN | PASS | PASS | Raw: provider_decision; trace 07a9909c-01f8-4e7e-85a7-d67d89fac6ae |
| 20_timeout_recovery | PASS | PASS | PASS | PASS | Raw: contract matched; trace 25925267-7fc2-4b21-80fe-8592147c015e |
| 21_expired | PASS | PASS | PASS | PASS | Raw: contract matched; trace 0607cb41-3826-486b-8e10-ca57609906cf |
| 22_superseded | PASS | PASS | PASS | PASS | Raw: contract matched; trace 8205fa63-13b1-485b-953c-47cd659bc27d |
| 23_conflicted | PASS | PASS | PASS | PASS | Raw: contract matched; trace d7a472f6-ddbc-43b6-a450-65c12e998660 |
| 24_confirmed | PASS | PASS | PASS | PASS | Raw: contract matched; trace 410e3976-4027-4395-8d3c-aebf789aa661 |
| 25_isolation_restart | PASS | PASS | PASS | PASS | Raw: contract matched; trace 01170c77-5d26-4850-808e-6e8760beb1e4 |
