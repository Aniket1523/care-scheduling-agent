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
| `20261113T063923Z` | `113367f` | all 6 | E1 E2 E4 E5 | | E3 E6 | 2 | Full run; two scenarios hit the quota |
| `20261113T064153Z` | `113367f` | E3 | E3 | | | 0 | E3 re-run |
| `20261113T064320Z` | `113367f` | E6 | E6 | | | 0 | E6 re-run |
| `20261113T123422Z` | `24d3c9a` (agent code unchanged since `113367f`) | all 6 | all 6 | | | 0 | **Final: first complete 6/6 run.** `--rebuild-baseline --record-evidence`; 40 model calls, 0 guard rejections |

**Final state: run `20261113T123422Z`, 6/6** (`evals/evidence/20261113T123422Z.json`). This is the
first complete live run of all six scenarios under the current checks: exit 0, no errors, no
regressions, 40 model calls, 0 claim-guard rejections.

| Scenario | E1 | E2 | E3 | E4 | E5 | E6 |
|---|---|---|---|---|---|---|
| Result | pass | pass | pass | pass | pass | pass |
| Model calls | 5 | 6 | 8 | 6 | 9 | 6 |

- Command: `python -m care_agent eval --rebuild-baseline --record-evidence`, model
  `gemini-3.5-flash-lite`.
- Code: the run started at 18:04:22 +05:30, about 3 minutes after commit `24d3c9a`. Source and
  tests are identical from `464a98d` to `24d3c9a`, and the agent's prompt, tools, guard and loop
  are unchanged since `113367f`. The evidence file does not record a commit hash or whether the
  working tree was clean; this mapping comes from timestamps.
- Baseline: the rebuild succeeded and wrote all six as `pass`. That is identical to the committed
  `evals/baseline.json`, so the file's content did not change (Git shows no difference). Since
  this run, the baseline's six `pass` entries are confirmed by one complete run under the current
  checks. They were first recorded in `20261112T160955Z` under the older M3 checks (copy in
  `evals/baseline-history/`).

**Earlier split verification on `113367f` (kept for the record):** every scenario passed at least
once, but not in one run. E1, E2, E4 and E5 passed in `063923Z`; E3 (`064153Z`) and E6 (`064320Z`,
also `063830Z`) passed when re-run alone after free-tier rate limits.

## Earlier runs (before `--record-evidence` existed)

Not recorded as evidence files; listed for context only.

- `20261112T160955Z`: the committed 6/6 baseline (M3 checks). Regraded offline during the M4.4
  review under the M4.4a authorisation checks: 5/6 (E6 escalated after the ambiguous
  "Yes, cancel it.").
- `20261112T181154Z`: 6/6 under the M3 checks; the run whose review led to M4.4. Regraded offline
  under the M4.4a checks: 3/6 (E2 wrote a second escalation for a repeated request; E5 booked a
  new appointment before the caller accepted it; E6 as above).

The offline regrades were review analysis with a scratch script, not recorded runs.

## Before/fix commit pairs (checked 2026-11-13)

For each improvement: the last commit before the fix, the fix commit, and whether a demonstration
can honestly show "fails before, passes after". "Eval works" means `python -m care_agent eval`
runs at that commit (checked in a separate worktree, importing that worktree's code: without a key
it reaches the configuration check and exits 2, as on `main`). "Scripted" means the scenario was
run through `run_eval` at that commit with the deterministic scripted agent from that commit's
`tests/test_evals.py` (no network).

| IMP | Scenario | Last commit before fix | Fix commit | Scenario existed before? | Eval works before? | Honest before/after demo? |
|---|---|---|---|---|---|---|
| IMP-001 | E3 | none: `0b9276c` has no agent | `7582822` (first agent commit) | No (harness from `2143a0b`) | No | **No.** The defect was never committed together with the harness; the "before" is a manual session. Do not demonstrate live. |
| IMP-002 | E4, E5 (claim-guard rejections) | `436dc22` | `715b239` | Yes | Yes | **No, misleading.** The effect is fewer guard rejections, not a pass/fail change: scripted E4, E5, E6 pass at both commits (checked), and real E4/E5 did not fail because of it. |
| IMP-003 | E6 (step 3) | `228481a` | `113367f` | Yes | Yes | **Live only, not guaranteed.** A prompt and tool-guidance fix: the scripted agent never escalates, so it passes at both. Recorded real runs: E6 failed at `228481a` (`063300Z`, one run) and passed at `113367f` (`063830Z`, `064320Z`). Gemini is not deterministic, so a live re-run may not reproduce either result. |
| IMP-004 | E2 | `715b239` | `c7c7352` | Yes | Yes | **Yes, the best pair.** Scripted E2 at `715b239`: fails `escalation_actions_match_records` and `actions_authorised`, exit 1, `REGRESSION: E2`. At `c7c7352`: passes, exit 0 (both checked). A live Gemini run fails only if the model escalates again on the repeated request, as it did in both real runs that reached that turn (`053628Z`, recorded; `181154Z`, offline regrade). Caveat: `c7c7352` also contains IMP-003 step 1 (prompt). |

Run `053628Z` (the "before" run) was made on the working tree just before commit `436dc22`, so it
cannot be tied to an exact commit.
