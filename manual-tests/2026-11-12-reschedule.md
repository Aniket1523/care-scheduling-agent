# Manual test: Maria reschedules her check-up (real Gemini)

Date: 2026-11-12
Type: **Manual interactive test** with the real Gemini model (`python -m care_agent chat`). Not a
deterministic automated evaluation; not graded by the eval harness.
Tester: Aniket Kangane
Milestone: M4.2

## Scenario

Maria Garcia (demo patient, DOB 1985-03-14) calls to move her existing check-up to Tuesday.

## Observed result (as reported by the tester)

| Step | Result |
|---|---|
| Identity verification | Succeeded using first name, last name and date of birth |
| Existing appointment | `apt_mariacheckup` (seeded check-up) |
| Requested new slot | Tuesday 17 November 2026, 09:00, Dr Lee |
| `reschedule_appointment` tool result | `status: ok`, `verified: true` |
| Agent's final confirmation | Accepted by the claim guard (delivered to the caller) |

`verified: true` on a reschedule result means the tool read the appointment back from the EHR after
the update and found it booked in the new slot (`ToolRunner._versioned_write`,
`src/care_agent/agent/tools.py`).

## Not captured

- Caller phone number used for the session.
- Exact wording of the conversation and of the agent's final reply.
- Raw tool arguments, action ID and model-call count. No diagnostic log or trace was saved.
- Session timestamps beyond the date.

Derived, not captured: in the demo seed for 12 November 2026, the Tuesday 09:00 Dr Lee slot has the
ID `slot_202611170900lee` (`src/care_agent/ehr/seed.py`, `demo_slots`).

## What this shows, and what it does not

- Shows: the real model completed a full verified write path (identity check, appointment lookup,
  version-checked reschedule, read-back, guarded confirmation) in one live session.
- Does not show: repeatability (one run), behaviour under faults, or anything the eval harness
  grades. Automated coverage of rescheduling is in `tests/test_agent.py`
  (`test_reschedule_is_verified_by_a_fresh_read`) and, under an out-of-band change, eval scenario E5.
