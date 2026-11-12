# IMP-NNN: <short title>

Status: Proposed | Approved | Implemented | Verified
Author: <human reviewer>
Date: YYYY-MM-DD

## Observed failure
- Scenario(s): E?
- Eval run: `runs/<run_id>/` (failed checks from `failures.json`)
- What happened, quoted from the trace (tool calls, results, agent reply):

## Root cause
What actually caused it, confirmed from the trace and code. Not the heuristic hint alone.

## Fix layer
prompt | tool | claim guard | identity | retry/reconciliation | EHR | scenario script (harness bug)

## Change
The smallest change that addresses the root cause. Files touched.
Confirm: no test weakened, no capability disabled, no scenario expectation loosened
(a harness bug fix must be explained separately).

## Expected effect
Which checks should now pass; which scenarios must stay passing.

## Result
| Scenario | Before | After |
|---|---|---|
| E? | fail | pass |

Score: before x/6, after y/6. Eval exit code: 0.
Commit: <hash>
