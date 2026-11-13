# Evaluation evidence

Compact, sanitised records of real-model evaluation runs, written by
`python -m care_agent eval --record-evidence`. Full traces stay in the git-ignored `runs/`
directory on the machine that ran them.

Each `<run_id>.json` holds the model name, exit code, score, baseline score and regressions, and
per scenario the status, check results, failed-check details (record IDs only), model calls,
claim-guard rejections, write attempts as (turn, tool), injected faults and the error type. It
holds no caller or agent text, no free-text tool arguments, no error messages and never the API key.

## Final result: `20261113T123422Z`, 6/6

`evals/evidence/20261113T123422Z.json` is the first complete live run of all six scenarios under
the current checks: exit 0, no errors, no regressions, 40 model calls and no claim-guard
rejections.

| Scenario | E1 | E2 | E3 | E4 | E5 | E6 |
|---|---|---|---|---|---|---|
| Result | pass | pass | pass | pass | pass | pass |
| Model calls | 5 | 6 | 8 | 6 | 9 | 6 |

- **Command and model:** `python -m care_agent eval --rebuild-baseline --record-evidence`,
  `gemini-3.5-flash-lite`.
- **Code:** the run started at 18:04:22 +05:30, about 3 minutes after commit `24d3c9a`. Source and
  tests are identical from `464a98d` to `24d3c9a`, and the agent's prompt, tools, guard and loop
  are unchanged since `113367f`. The evidence file records neither a commit hash nor whether the
  working tree was clean, so this attribution comes from timestamps.
- **Baseline:** the rebuild succeeded and wrote all six as `pass`, which is identical to the
  committed `evals/baseline.json`, so the file's content did not change (Git shows no difference).
  The six `pass` entries, first recorded in `20261112T160955Z` under the older M3 checks (copy in
  `evals/baseline-history/`), are now confirmed by a complete run under the current checks.

## Comparing runs

Every run below used `gemini-3.5-flash-lite` (set with `LLM_MODEL`), but not every run used the
same checks. `20261113T053628Z` predates `ledger_matches_ehr`, which was added with IMP-004
(`c7c7352`); every later run includes it. Its E2 and E6 failures were on checks that all later runs
share (`escalation_actions_match_records`, `actions_authorised`), so those scenario-level changes
are comparable, but its overall score is not directly comparable with later totals.

"Code" is the latest commit before the run, from commit and run timestamps. `error` means a Gemini
API error (429 RESOURCE_EXHAUSTED on the free tier): it is not graded and never counts as a pass.

| Run | Code | Scenarios | Pass | Fail | Error | Exit | Notes |
|---|---|---|---|---|---|---|---|
| `20261113T053628Z` | working tree before `436dc22` (before IMP-002/003/004) | all 6 | E1 E3 | E2 E6 | E4 E5 | 1 | **Before.** E2: second escalation write for a repeated request; E6: escalation without an accepted offer. No `ledger_matches_ehr` |
| `20261113T061645Z` | `c7c7352` (IMP-002, IMP-003 step 1, IMP-004) | all 6 | E1 E2 E3 E4 | | E5 E6 | 2 | E2 fixed |
| `20261113T062135Z` | `c7c7352` | E5 E6 | | E5 E6 | | 1 | Unaccepted escalations (led to IMP-003 step 2) |
| `20261113T062940Z` | `228481a` (IMP-003 step 2) | E5 E6 | E5 | | E6 | 2 | E5 fixed |
| `20261113T063300Z` | `228481a` | E6 | | E6 | | 1 | Escalation in the turn of a failed retry (led to IMP-003 step 3) |
| `20261113T063830Z` | `113367f` (IMP-003 step 3) | E6 | E6 | | | 0 | |
| `20261113T063923Z` | `113367f` | all 6 | E1 E2 E4 E5 | | E3 E6 | 2 | Full run; two scenarios hit the quota |
| `20261113T064153Z` | `113367f` | E3 | E3 | | | 0 | E3 re-run |
| `20261113T064320Z` | `113367f` | E6 | E6 | | | 0 | E6 re-run |
| `20261113T123422Z` | `24d3c9a` (agent code unchanged since `113367f`) | all 6 | all 6 | | | 0 | **Final: first complete 6/6 run**; baseline rebuilt; 40 model calls, 0 guard rejections |

Before the final run, the improved code (`113367f`) had passed every scenario at least once, but
not in one run: E1, E2, E4 and E5 in `063923Z`, and E3 (`064153Z`) and E6 (`064320Z`, also
`063830Z`) when re-run alone after free-tier rate limits.

## Earlier runs, before evidence recording existed

These have no evidence files; their traces are on the development machine only.

- `20261112T160955Z`: the committed 6/6 baseline, graded with the M3 checks. Regraded offline during
  the M4.4 review under the M4.4a authorisation checks: 5/6 (E6 escalated after the ambiguous
  "Yes, cancel it.").
- `20261112T181154Z`: 6/6 under the M3 checks; its review led to M4.4. Regraded offline under the
  M4.4a checks: 3/6 (E2 wrote a second escalation for a repeated request; E5 booked a new
  appointment before the caller accepted it; E6 as above).

The offline regrades were review analysis with a scratch script, not recorded runs.

## Before/fix commit pairs (checked 2026-11-13)

For each improvement, the last commit before the fix, the fix commit, and whether a demonstration
can honestly show "fails before, passes after". "Eval works" means `python -m care_agent eval` runs
at that commit; this was checked in a separate worktree importing that worktree's code, where
without a key it reaches the configuration check and exits 2, as on `main`. "Scripted" means the
scenario was run through `run_eval` at that commit with the deterministic scripted agent from that
commit's `tests/test_evals.py`, with no network.

| IMP | Scenario | Last commit before fix | Fix commit | Scenario existed before? | Eval works before? | Honest before/after demo? |
|---|---|---|---|---|---|---|
| IMP-001 | E3 | none: `0b9276c` has no agent | `7582822` (first agent commit) | No (harness from `2143a0b`) | No | **No.** The defect was never committed together with the harness; the "before" is a manual session. Do not demonstrate live. |
| IMP-002 | E4, E5 (claim-guard rejections) | `436dc22` | `715b239` | Yes | Yes | **No, misleading.** The effect is fewer guard rejections, not a pass/fail change: scripted E4, E5 and E6 pass at both commits (checked), and real E4/E5 did not fail because of it. |
| IMP-003 | E6 (step 3) | `228481a` | `113367f` | Yes | Yes | **Live only, not guaranteed.** A prompt and tool-guidance fix: the scripted agent never escalates, so it passes at both. Recorded real runs: E6 failed at `228481a` (`063300Z`, one run) and passed at `113367f` (`063830Z`, `064320Z`). Gemini is not deterministic, so a live re-run may not reproduce either result. |
| IMP-004 | E2 | `715b239` | `c7c7352` | Yes | Yes | **Yes, the best pair.** Scripted E2 at `715b239` fails `escalation_actions_match_records` and `actions_authorised` (exit 1, `REGRESSION: E2`); at `c7c7352` it passes (exit 0). Both checked. A live Gemini run fails only if the model escalates again on the repeated request, as it did in both real runs that reached that turn (`053628Z`, recorded; `181154Z`, offline regrade). `c7c7352` also contains IMP-003 step 1 (prompt). |

Run `053628Z` was made on the working tree just before commit `436dc22`, so it cannot be tied to an
exact commit.
