# Design Note

The agent must never tell a caller that something happened unless the EHR shows it. A tool
returning "ok" is not proof, and neither is the model saying so; the design follows from that.

## Architecture and tool flow

Plain Python, no agent framework. `agent/loop.py` drives Gemini with automatic function calling
disabled, so every tool call goes through the project's own dispatcher, with at most 8 model calls
per caller turn. Tools (`agent/tools.py`) call an in-process SQLite mock EHR (`ehr/`) whose
`FaultPlan` can time out before or after a commit, or raise an error after one.

1. **Identity:** `verify_identity` needs first name, last name and date of birth. The calling
   number is only a hint (F3); `patient_id` comes from the verified session, never from the model.
2. **Reads** return typed IDs; an ID with the wrong prefix (a `svc_` as an appointment) is
   rejected before it reaches the EHR (F4).
3. **Writes** get one `action_id` per logical operation, reused for up to 3 attempts. After a
   timeout or error the tool reads the EHR to decide whether the write happened, a retry is safe,
   or someone else changed the record (F1, F2, F5). `verified: true` only when a fresh read shows
   the change; the outcome goes into a per-call ledger.
4. **Replies** go only through `reply_to_patient(message, confirmed_action_ids)`. The claim guard
   checks them against the ledger, and "Confirmed:" lines are rendered from verified EHR data.
   After two rejected replies, the caller gets a fallback built from the ledger.

## Decisions and trade-offs

- **Evidence, not wording.** Wording patterns only classify a free-text sentence as a claim; the
  evidence for it must be a verified action or a fresh EHR observation in the ledger.
- **Write safety in code:** idempotency keys and version-checked updates stop duplicate and stale
  writes, whatever the model asks for.
- **Consent is a prompt rule plus an evaluation check (ADR-020), not runtime enforcement.** That
  fitted the time budget, but an unauthorised write is detected afterwards, not blocked.
- **Deterministic grading:** scripted caller, fixed clock, fresh database; checks read EHR state,
  the ledger and structured claims. No LLM judge.

## How the loop works

`python -m care_agent eval` runs E1–E6 (F1–F5, plus a cancellation that never commits) and writes
traces and `failures.json`. Exit 1 means a scenario that passed in `evals/baseline.json` now fails;
exit 2 means the run could not complete. Each genuine failure gets a human-reviewed record
(`improvements/IMP-NNN.md`), a fix in its own commit with tests, and a re-run of the same scenarios.

## Before and after (real Gemini, `gemini-3.5-flash-lite`)

| | E1 | E2 | E3 | E4 | E5 | E6 | Score |
|---|---|---|---|---|---|---|---|
| Before: `053628Z` | pass | **fail** | pass | error (429) | error (429) | **fail** | incomplete |
| After: `123422Z` | pass | pass | pass | pass | pass | pass | **6/6** |

`20261113T123422Z` is one complete live run on `gemini/gemini-3.5-flash-lite`: 40 model calls,
exit 0, no errors, regressions or claim-guard rejections. It also rebuilt the regression baseline,
whose content was already six `pass` and did not change.

The check sets differ: `053628Z` predates `ledger_matches_ehr` (added with IMP-004). E2 and E6
failed there on checks both runs share (`escalation_actions_match_records`, `actions_authorised`),
so those fail→pass changes are comparable; the totals are not. There is no complete "before"
score, and an earlier 6/6 (`160955Z`) used weaker checks.

## Limitations

- One run per scenario on a non-deterministic model: a pass is evidence, not proof.
- Consent is graded, not enforced; the authorisation check cannot see which offer was accepted.
- Callers are scripted; an unusually worded false claim can slip past the wording check.

## One thing to change for a real clinic

Run the ledger-versus-EHR checks (`ledger_matches_ehr`, `claims_match_ehr`) after every live call
and send any mismatch to staff the same day, before the patient misses the appointment.
