# Design Note

**Invariant:** the agent never tells a caller something happened unless the EHR shows it.

## Architecture and tool flow

Python, no agent framework. `agent/loop.py` drives Gemini with automatic function calling off, and
makes at most 8 model calls per caller turn. Tools (`agent/tools.py`) call an in-process SQLite mock
EHR (`ehr/`). Its `FaultPlan` can time out before or after commit, or raise an error after commit.

1. `verify_identity` needs first name, last name and date of birth. The phone number is only a
   hint (F3). `patient_id` comes from the verified session, never from the model.
2. Reads return typed IDs. An ID with the wrong prefix (a `svc_` given as an appointment) is
   rejected (F4).
3. Each write has one `action_id` and up to 3 attempts. After a failure, the tool reads the EHR and
   decides: the write happened, a retry is safe, or the record changed elsewhere (F1, F2, F5).
   `verified: true` only after a fresh read shows the change.
4. The model replies only through `reply_to_patient(message, confirmed_action_ids)`. The claim
   guard checks the reply against the call's ledger, and "Confirmed:" lines are built from verified
   EHR data. After two rejected replies, a fallback reply built from the ledger is sent.

## Key choices and why

- **Structured evidence over wording:** the model must cite the verified action; wording checks
  are only a backstop.
- **Write safety in code:** idempotency keys and version-checked writes stop duplicate or stale
  writes, whatever the model does.
- **Consent is a prompt rule plus an evaluation check (ADR-020), not runtime enforcement.** This
  fitted the time budget, but consent errors are caught afterwards, not blocked.
- **Deterministic grading:** scripted caller, fixed clock, fresh database; checks read EHR state,
  the ledger and structured claims. No LLM judge.

## How the loop works

`python -m care_agent eval` runs E1–E6 (F1–F5, plus a cancellation that never commits). It writes
traces and `failures.json`. Exit 1 means a scenario that passed in `evals/baseline.json` now fails;
exit 2 means the run could not complete (for example, an API error). A human writes
`improvements/IMP-NNN.md` (root cause, fix layer, change). The fix lands in its own commit with
tests, and the same scenarios are run again. `--record-evidence` saves a sanitised summary to
`evals/evidence/`.

## Before and after (real Gemini, `gemini-3.5-flash-lite`, current checks)

| | E1 | E2 | E3 | E4 | E5 | E6 | Score |
|---|---|---|---|---|---|---|---|
| Before: `053628Z` | pass | **fail** | pass | error (429) | error (429) | **fail** | incomplete |
| After: `123422Z` | pass | pass | pass | pass | pass | pass | **6/6** |

`123422Z` is one complete live run of all six scenarios (exit 0, no errors, no regressions, 0
claim-guard rejections). It also rebuilt the regression baseline, whose content was already six
`pass` and did not change. The measured fail→pass changes are E2 (IMP-004) and E6 (IMP-003). There
is no complete "before" score, because two scenarios hit the rate limit. An earlier 6/6 (`160955Z`)
used weaker checks and is not comparable.

## Limitations

- One run per scenario on a non-deterministic model: a pass is evidence, not proof.
- Consent is graded, not enforced, and the authorisation check cannot see which offer the caller
  accepted.
- Callers are scripted; an unusually worded false claim can pass the wording check.

## One thing to change for a real clinic

Run the ledger-vs-EHR checks (`ledger_matches_ehr`, `claims_match_ehr`) after every live call, and
send any mismatch to staff the same day, before the patient misses the appointment.
