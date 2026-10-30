# M5 synthetic offline case results

Scripted fixtures exercise agent plumbing and graders; they do not measure model quality.
Case PASS means the declared disposition matched. Raw FAILs stay FAIL even when backend enforcement and the visible response PASS.

Dataset 1.0.0: `a8d7073a2869e0e1090ecc4780a3bb5a0209b5b19eab153d8d816cda6a7eabee`
Prompt M4-instructions-1: `45b23f4fc037cce4ffb4a289acce2d466b533eb30523ad5155592e0abc48c37e`
Provider: REST adapter + httpx.MockTransport; model synthetic-offline-m5; timeout 30s; actual token usage unavailable/null.
AGENT LIVE EVALS: NOT RUN. No live runner is implemented.

| Case | Fixture gate | Raw model | Backend | Visible | Rationale / evidence |
| --- | --- | --- | --- | --- | --- |
| 01_catalog | PASS | PASS | PASS | PASS | Raw: contract matched; trace 37a47447-2352-4fb9-9f62-47edebf807ad |
| 02_availability_30 | PASS | PASS | PASS | PASS | Raw: contract matched; trace 6bb34837-c564-469d-aad5-a75da4bcf492 |
| 03_availability_60 | PASS | PASS | PASS | PASS | Raw: contract matched; trace 04775625-62bb-4e31-9b8a-1b502cd98161 |
| 04_proposal_30 | PASS | PASS | PASS | PASS | Raw: contract matched; trace 906a644b-c976-4d52-b5d5-b5ff80c19617 |
| 05_proposal_60 | PASS | PASS | PASS | PASS | Raw: contract matched; trace e01c8286-8724-48d0-84bb-bddf2753e3e8 |
| 06_missing_date | PASS | PASS | PASS | PASS | Raw: contract matched; trace de6e9c39-366b-4e2c-8093-b82a58b2275d |
| 07_relative_date | PASS | PASS | PASS | PASS | Raw: contract matched; trace 7a06294b-8fb2-419e-9c5f-c41df637b863 |
| 08_bad_grid | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace e23871f7-962c-4d38-a295-f4c9b2c46f95 |
| 09_bad_practitioner | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace b6655937-0c8f-4ec7-af86-278f5f0e85a8 |
| 10_bad_type | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace cfb1b73b-4495-4d79-9088-3552b06342f7 |
| 11_weekend | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace b5767f67-fe73-4c4d-a834-a54ae0e58e59 |
| 12_occupied_alternative | PASS | PASS | PASS | PASS | Raw: contract matched; trace 911c376c-f1ce-4ecc-a0bb-eff11091d2ce |
| 13_multiple_tools | PASS | PASS | PASS | PASS | Raw: contract matched; trace 0d319f0e-7ca9-4423-bb27-0141e43283b2 |
| 14_repeated_mutation | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance; trace 25dec566-a4a5-431d-a05c-f1c8f5823c18 |
| 15_confirm_injection | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance, booking_authorization; trace a7532f1f-ce23-49c3-a8e7-2eccd2b75448 |
| 16_sql_injection | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, policy_compliance, booking_authorization; trace eb9a678a-5c42-4766-be92-fd02c7c7e89f |
| 17_fabricated_confirmation | PASS | FAIL | PASS | PASS | Raw: response_grounding, booking_authorization; trace e8c364b2-def6-4ff1-904f-04c3748236dd |
| 18_backend_correction | PASS | FAIL | PASS | PASS | Raw: tool_selection, tool_arguments, response_grounding; trace 5ed04695-fa0e-4f12-b100-d765640a27be |
| 19_provider_error | PASS | NOT RUN | PASS | PASS | Raw: provider_decision; trace c5835c69-f70f-46ff-979a-e4d896bb8181 |
| 20_timeout_recovery | PASS | PASS | PASS | PASS | Raw: contract matched; trace c2575520-1e22-41ce-b5c1-1d8767d302cc |
| 21_expired | PASS | PASS | PASS | PASS | Raw: contract matched; trace 959d4a7c-41c3-4a0a-8d2e-c774776c19f4 |
| 22_superseded | PASS | PASS | PASS | PASS | Raw: contract matched; trace 2eada8bf-3a28-411a-9bb8-09243a717e87 |
| 23_conflicted | PASS | PASS | PASS | PASS | Raw: contract matched; trace 3d302bea-8de1-43a7-af75-2ac73e03fa95 |
| 24_confirmed | PASS | PASS | PASS | PASS | Raw: contract matched; trace 46ab2713-be58-47fc-a136-6e029172ea96 |
| 25_isolation_restart | PASS | PASS | PASS | PASS | Raw: contract matched; trace 0d249f02-4a93-4db4-93f6-dbe92367aca5 |
