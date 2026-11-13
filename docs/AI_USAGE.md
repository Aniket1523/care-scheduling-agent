# AI Usage

The assignment asks where AI helped and where my own judgment overrode it.

I used Claude Code (Claude Opus 5.5) as the primary implementation engineer throughout. It wrote
most of the code, the tests and the first drafts of the documentation, including the improvement
records. I set the scope and constraints, reviewed and approved each milestone before it was
committed, ran the real-Gemini sessions and evaluations, and made the decisions in the last table
below. Entries were added as the work happened; the last ones cover the final documentation pass.

## Where Claude Code helped

| Date | Milestone | What it did |
|---|---|---|
| 2026-11-12 | Design | Read the assignment and produced the requirements breakdown, traceability matrix, domain model, schema, tool contracts, evaluation and improvement-loop design, risks and milestone plan (`docs/internal/ANALYSIS.md`). |
| 2026-11-12 | Design | Drafted the decision records (`docs/design/DECISIONS.md`), the progress tracker and `CLAUDE.md`. |
| 2026-11-12 | M0 | Wrote the project skeleton: `pyproject.toml`, the environment-based config module, CLI placeholders, pytest tests and the Ruff config. |
| 2026-11-12 | M0 review | Reviewed its own M0 code on request. An empirical probe found secret-leak paths (retained exception context, construction and assignment errors), plus a duplicated version, a missing real-process exit-code test and an unpinned Ruff. |
| 2026-11-12 | M1a | Wrote typed IDs, the Patient and Appointment models, the SQLite schema and repository, and 24 tests. Its self-review caught two test problems before reporting: an import that only worked under `python -m pytest`, and a "rollback" test that could not fail, which was rewritten and checked with a deliberate autocommit mutation. |
| 2026-11-12 | M1b | Wrote the EHR operations (identity resolution, patient creation, booking, cancellation, atomic rescheduling) and 35 tests. Chose Python-side `casefold()` name matching after noting that SQLite's `lower()` only folds ASCII. |
| 2026-11-12 | M1c | Wrote idempotent booking and escalation, fault injection and version-checked cancel/reschedule, with 22 tests. Found that nested `with conn:` blocks commit early in Python's sqlite3 and moved transaction ownership from repository writes to the service. Checked by mutation that the retry tests depend on the idempotency lookup. |
| 2026-11-12 | M2 | Wrote the Gemini-backed agent: tools, claim guard, loop, chat CLI, demo seed and 36 fake-model tests. Mutation checks showed the retry-after-transient-timeout path was untested (the read-back alone hid it), so it added two tests that catch it. |
| 2026-11-12 | M3 | Wrote the evaluation harness (scenarios, runner, grading, traces, failure reports, regression gate) and 16 tests. A harness test caught its own bug in the E1 expectation (an exact count reported a missing booking as a duplicate) before any real run. |
| 2026-11-13 | M4.4a | Added the action-authorisation and E2 consistency checks, tool-layer trace events, guard-rejection counts and sanitised evidence output, with tests. I corrected this design twice; see the last table. |
| 2026-11-13 | M4.4b | Implemented IMP-002 (action versus state claims, EHR observations in the ledger, the single-record evidence rule, the grader split, two prompt lines) with 13 tests. The progress log from the time says it ran the new tests against the old guard to show they catch the false positives; that run was not recorded and cannot be repeated unchanged (see IMP-002). |
| 2026-11-13 | M4.4c | Implemented IMP-003 step 1 (the prompt's consent section) and IMP-004 (created/already-requested escalation outcomes, replay-first order, unique-index race handling, ledger record IDs, `ledger_matches_ehr`) with 11 tests. Rewrote its own first draft of the prompt, which quoted E6's exact caller line, as a general rule so the evaluation is not overfitted (now tested). |
| 2026-11-13 | M4.4c | Implemented IMP-003 steps 2 and 3 with tests (multi-option offers; wait for the caller before escalating after a failed action), after the real runs `062135Z` and `063300Z`. I specified the step-3 fix: the guidance wording, the rules and the constraints. |
| 2026-11-13 | M6 | Drafted `docs/DESIGN.md`, `docs/INCIDENT.md`, the evidence index and `improvements/IMP-002.md` (the fix had been committed without a record). Checked every score claim against the evidence files and commit timestamps, and ran the tests, Ruff and a secrets and ignored-files check. |
| 2026-11-13 | M6 | Worked through my final task list: proved E6's `checkup_unchanged` can fail (the docs had said it could not), added rate-limit pacing and backoff and `--rebuild-baseline`, checked before/fix commit pairs in separate worktrees with the scripted agent, and edited the reviewer-facing documents. |

## Where Claude Code was wrong

| Date | What it got wrong | How it was found | Resolution |
|---|---|---|---|
| 2026-11-12 | M0 review: claimed Pydantic's `hide_input_in_errors=True` would also stop frozen-assignment errors echoing the value. | The new assignment test failed: Pydantic 2.14 builds the frozen-instance error in Python without `hide_input`. | `LLMSettings.__setattr__` raises `TypeError("LLMSettings is immutable")`, which never includes the value. An intermediate version rebuilt a `ValidationError` with `hide_input=True`; I simplified it. |
| 2026-11-12 | M2: `verify_identity` accepted only ISO dates of birth (`date.fromisoformat`), and the fake-model tests only ever sent ISO. | My first real Gemini session (Maria calling from Luis's phone, "14 March 1985") could not verify her. Probing the real dispatcher showed every non-ISO date of birth returned INVALID_ARGUMENT; the EHR lookup was correct. | The tool now accepts unambiguous forms (ISO, month as a word) and still rejects all-numeric dates; regression tests confirmed to fail on the old parser. |
| 2026-11-12 | M2: the tool result envelope always included `verified` (default false), on reads and identity checks too, while the prompt said to claim things only when `verified=true`. | Real Gemini diagnostics from my session: `verify_identity` matched Maria but returned `verified: false`, and Gemini said no record was found. The fake-model tests never read that field on identity results. | IMP-001: `verified` and `action_id` only on write results, `identity_status` on every identity result, the prompt explains both; regression tests confirmed to fail on the old envelope. |
| 2026-11-12/13 | M2: the claim guard treated any cancellation wording as "the agent cancelled it". | Not caught by tests. The real run `20261112T181154Z` showed the guard rejecting true "already cancelled" replies in E4 and E5; in E5 the model then booked an appointment nobody asked for. | IMP-002 (action versus state claims, 13 tests); IMP-003 for the booking. |
| 2026-11-13 | IMP-003 steps 1 and 2: prompt rules that passed every deterministic test. | Real Gemini runs: `062135Z` (E5 and E6 still escalated without acceptance) and `063300Z` (E6 escalated in the turn of a failed retry). Fake-model tests can show a rule is in the prompt, not that the model follows it. | Step 3 changed the failed-write guidance the model reads at that moment; E6 then passed (`063830Z`, `064320Z`). |

## Where my judgment overrode it

| Date | Claude Code's proposal | My decision | Reason |
|---|---|---|---|
| 2026-11-12 | LLM-driven patient simulator, an LLM judge for claim extraction, 3 trials per scenario | Scripted patient, no LLM judge, a single trial initially | Determinism and cost; grading I can explain |
| 2026-11-12 | About 12 scenarios | 8–10 scenarios; six were built (one per failure pattern, plus E6) | Focus on the core failure modes within the time budget |
| 2026-11-12 | Let the LLM draft improvement records | Failure reports are automatic; improvement records are human-reviewed; no automatic code changes. In practice Claude Code drafted each record and I reviewed it. | A person stays accountable for every change |
| 2026-11-12 | A fingerprint of (call, operation, arguments) decides retry versus new intention | A unique `action_id` per logical operation, reused across retries; the fingerprint only rejects key reuse with different arguments | Guessing intent from arguments can merge a genuine repeat request with an earlier one |
| 2026-11-12 | Claim guard as a structured check plus a keyword backstop | Kept, with structured ledger outcomes primary and keywords never relied on alone | Keyword matching is brittle |
| 2026-11-12 | uv and mypy, Python 3.14 as the minimum | pip, pytest and Ruff only; `requires-python >= 3.12` | Fewer tools, and portable for reviewers |
| 2026-11-12 | M1b identity lookup treated a unique phone match (no name or date of birth) as a matched patient | The phone is only a hint; identity needs first name, last name and date of birth, and missing details return `verification_required` (ADR-019) | Caller ID can belong to someone else (F3) or be spoofed |
| 2026-11-12 | A small custom `.env` reader | Removed; environment variables are read directly | Avoid unnecessary code |
| 2026-11-12 | PowerShell commands in the docs | Windows CMD commands | The shell I actually use |
| 2026-11-13 | M4.4a check design | Escalations must be graded by `actions_authorised` too, and generic ledger/record checks must wait for record IDs (IMP-004) | An unrequested escalation is still an unauthorised action |
| 2026-11-13 | E6 interpretation (open question in the M4.4 review: does "Yes, cancel it." accept an offered callback?) | It does not (ADR-020), and the scenario script stays as committed rather than being reworded after seeing failures | Changing the test to match the model would hide the defect |
| 2026-11-13 | IMP-003 step 3, after run `063300Z` (who first diagnosed that run is not recorded) | The failed-write guidance says to offer a callback and wait, never escalate in the turn of a failed action; prompt and evaluator only, no runtime enforcement, no scenario wording | The model acts on the tool result it has just read, and a prompt rule alone had failed twice |
| 2026-11-13 | Reporting the final results | Report the verification as split across runs (free-tier 429s on E3 and E6) rather than as one 6/6 run, and claim no score movement without a recorded before/after. A later complete run, `20261113T123422Z`, then passed 6/6. | Honest evidence over a clean-looking number |
