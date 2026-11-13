# Incident: "The agent said it was cancelled; it is still on my schedule"

**How I find the cause.** The EHR does not record which call changed an appointment, so I find
the call from the patient and the time of the call, then read its trace and compare what the agent
said, what the ledger recorded, and what the EHR shows. Our E6 scenario is this incident, with
every cancellation attempt timing out before commit (run `20261113T064320Z`):

1. `tool_call cancel_appointment(apt_mariacheckup)` → `tool_result status: failed, NOT_CONFIRMED,
   verified: false`.
2. Internal events: `fault_injected timeout_before_commit` → `tool_attempt 1: timeout` →
   `reconcile_read: booked ... (version 1)`, repeated for attempts 2 and 3: the write never
   committed, so each retry was safe.
3. `reply_to_patient`, with `confirmed_action_ids: []`: "I wasn't able to cancel your check-up".
   Final `ledger`: one `cancel_appointment` with status `failed`. `ehr_state`: the appointment is
   `booked`.

In the reported incident the "said" step would disagree with the ledger or the EHR. Which one tells
you the cause:

- **Agent said cancelled, but the ledger has no verified cancel.** The claim guard missed the
  claim. Fix the guard and add the sentence as a test.
- **Ledger has a verified cancel of a different appointment.** The agent cancelled the wrong one
  (F4-style ID error).
- **Ledger has a verified cancel of the right appointment, but the EHR shows it booked.**
  Something changed it after the call, or the clinic's schedule reads a different copy (F5).

**What would have caught it first.** For a cancellation that never commits, the claim guard
rejects the false reply at runtime (`test_cancel_that_never_commits_falls_back_to_the_truth`), and
E6 in the regression gate fails if that ever stops working. For the cases the guard cannot see,
the same `claims_match_ehr` and `ledger_matches_ehr` checks should run after every live call and
alert staff the same day.

**Gap:** only the eval runner saves traces. The `chat` CLI and the mock EHR keep no per-call log
or audit table, and a production system would need both.
