# Evaluation evidence

Compact, sanitised records of real-model evaluation runs, written by
`python -m care_agent eval --record-evidence`. Full traces stay in the git-ignored `runs/`
directory on the machine that ran them.

Each `<run_id>.json` holds: model name, exit code, score, baseline score, regressions, and per
scenario the status, check results, failed-check details (record IDs only), model calls,
claim-guard rejections, write attempts as (turn, tool), injected faults and the error type. No
caller or agent text, no free-text tool arguments, no error messages, never the API key.

## Runs

All runs use `gemini-3.5-flash-lite` (set with `LLM_MODEL`) and the M4.4a checks. "Code" is the
latest commit the run was made on (from commit and run timestamps). `error` means a Gemini API
error (429 RESOURCE_EXHAUSTED on the free tier): it is not graded and never counts as a pass.

| Run | Code | Scenarios | Pass | Fail | Error | Exit | Key findings |
|---|---|---|---|---|---|---|---|
| `20261113T053628Z` | M4.4a checks, before IMP-002/003/004 | all 6 | E1 E3 | E2 E6 | E4 E5 | 1 | **Before.** E2: second escalation write for a repeated request; E6: escalation without accepted offer |
| `20261113T061645Z` | `c7c7352` (IMP-002, IMP-003 step 1, IMP-004) | all 6 | E1 E2 E3 E4 | | E5 E6 | 2 | E2 fixed |
| `20261113T062135Z` | `c7c7352` | E5 E6 | | E5 E6 | | 1 | Unaccepted escalations (IMP-003 step 2) |
| `20261113T062940Z` | `228481a` (IMP-003 step 2) | E5 E6 | E5 | | E6 | 2 | E5 fixed |
| `20261113T063300Z` | `228481a` | E6 | | E6 | | 1 | Escalation in the turn of a failed retry (IMP-003 step 3) |
| `20261113T063830Z` | `113367f` (IMP-003 step 3) | E6 | E6 | | | 0 | |
| `20261113T063923Z` | `113367f` | all 6 | E1 E2 E4 E5 | | E3 E6 | 2 | **Final full run**; two scenarios hit the quota |
| `20261113T064153Z` | `113367f` | E3 | E3 | | | 0 | Final E3 |
| `20261113T064320Z` | `113367f` | E6 | E6 | | | 0 | Final E6 |

**Final state:** on the final code (`113367f`) every scenario has passed at least once: E1, E2,
E4, E5 in `063923Z`, E3 in `064153Z`, E6 in `064320Z` (and `063830Z`). This was **not** one clean
6/6 run: the full run lost E3 and E6 to the free-tier rate limit and they were re-run on their own.
No scenario failed on the final code.

## Earlier runs (before `--record-evidence` existed)

Not recorded as evidence files; listed for context only.

- `20261112T160955Z`: the committed 6/6 baseline (M3 checks). Regraded offline during the M4.4
  review under the M4.4a authorisation checks: 5/6 (E6 escalated after the ambiguous
  "Yes, cancel it.").
- `20261112T181154Z`: 6/6 under the M3 checks; the run whose review led to M4.4. Regraded offline
  under the M4.4a checks: 3/6 (E2 wrote a second escalation for a repeated request; E5 booked a
  new appointment before the caller accepted it; E6 as above).

The offline regrades were review analysis with a scratch script, not recorded runs.
