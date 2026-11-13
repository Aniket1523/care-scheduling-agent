# Evaluation evidence

Compact, sanitised records of real-model evaluation runs, written by
`python -m care_agent eval --record-evidence`. Full traces stay in the git-ignored `runs/`
directory on the machine that ran them.

Each `<run_id>.json` holds: model name, exit code, score, baseline score, regressions, and per
scenario the status, check results, failed-check details (record IDs only), model calls,
claim-guard rejections, write attempts as (turn, tool), injected faults and the error type. No
caller or agent text, no free-text tool arguments, no error messages, never the API key.

## Runs

| Run | Label | Harness | Score | Exit | Key findings |
|---|---|---|---|---|---|
| _to be added_ | M4.4 before | M4.4a checks | | | |
| _to be added_ | M4.4 after | M4.4a checks + IMP-002/003/004 | | | |

## Earlier runs (before `--record-evidence` existed)

Not recorded as evidence files; listed for context only.

- `20261112T160955Z`: the committed 6/6 baseline (M3 checks). Regraded offline during the M4.4
  review under the M4.4a authorisation checks: 5/6 (E6 escalated after the ambiguous
  "Yes, cancel it.").
- `20261112T181154Z`: 6/6 under the M3 checks; the run whose review led to M4.4. Regraded offline
  under the M4.4a checks: 3/6 (E2 wrote a second escalation for a repeated request; E5 booked a
  new appointment before the caller accepted it; E6 as above).

The offline regrades were review analysis with a scratch script, not recorded runs.
