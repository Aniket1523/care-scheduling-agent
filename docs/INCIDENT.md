# Incident: "The agent said it was cancelled; it is still on my schedule"

**Finding the cause.** Three sources have to agree: what the agent said, what its ledger recorded,
and what the EHR shows. The EHR does not record which call changed an appointment, so I would find
the call from the patient and the time, read its trace, and look for the first place they diverge.
E6 reproduces the risky condition, a cancellation that never commits, so its trace shows what each
source should contain (run `20261113T064320Z`):

1. `tool_call cancel_appointment(apt_mariacheckup)` → `tool_result status: failed, NOT_CONFIRMED,
   verified: false`.
2. Tool-layer events: `fault_injected timeout_before_commit` → `tool_attempt 1: timeout` →
   `reconcile_read: booked ... (version 1)`, repeated for attempts 2 and 3. The write never
   committed, so each retry was safe.
3. `reply_to_patient` with `confirmed_action_ids: []`: "I wasn't able to cancel your check-up".
   Final `ledger`: one `cancel_appointment` with status `failed`; `ehr_state`: the appointment is
   `booked`.

In the clinic's case the reply said "cancelled", so the question is which source disagrees with it:

- **No verified cancel in the ledger:** the claim guard let an unsupported claim through. Fix the
  guard and add that sentence as a test.
- **A verified cancel of a different appointment:** the agent cancelled the wrong one (an F4-style
  ID error).
- **A verified cancel of the right appointment, but the EHR shows it booked:** something changed
  it after the call, or the clinic's schedule reads a different copy (F5).

**What would have caught it first.** For a cancellation that never commits, the claim guard rejects
the false reply at runtime (`test_cancel_that_never_commits_falls_back_to_the_truth`), and E6 in
the regression gate fails if that protection ever breaks. For the cases the guard cannot see, the
same `claims_match_ehr` and `ledger_matches_ehr` checks should run after every live call and alert
staff the same day.

**Gap:** only the eval runner saves traces. The `chat` CLI and the mock EHR keep no per-call log or
audit table; a production system would need both before this investigation is possible.
