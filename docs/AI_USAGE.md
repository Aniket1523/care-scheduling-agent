# AI Usage Log

The assignment asks where AI helped and where human judgment overrode it. Entries are added as work
happens, not reconstructed at the end.

Tool: Claude Code (Claude Opus 5.5) as the primary implementation engineer; the product owner / tech
lead reviews and approves every milestone.

## Where AI helped

| Date | Milestone | What AI did |
|---|---|---|
| 2026-11-12 | Design | Read the assignment; produced requirements breakdown, traceability matrix, domain model, schema, tool contracts, evaluation and improvement-loop design, risks and milestone plan (`docs/internal/ANALYSIS.md`). |
| 2026-11-12 | Design | Drafted decision records (`docs/design/DECISIONS.md`), progress tracker and `CLAUDE.md`. |
| 2026-11-12 | M0 | Wrote the project skeleton: `pyproject.toml`, env-based config module, CLI placeholders, pytest tests, Ruff config. |
| 2026-11-12 | M1a | Wrote typed IDs, Patient/Appointment models, SQLite schema and repository, and 24 tests. Self-review caught two test problems before reporting: an import that only worked under `python -m pytest`, and a "rollback" test that could not fail; the latter was rewritten and checked with a deliberate autocommit mutation. |
| 2026-11-13 | M6 final tasks | On the owner's task list: proved E6's `checkup_unchanged` can fail (the doc had said it could not), added rate-limit pacing and backoff, `--rebuild-baseline`, checked before/fix commit pairs in separate worktrees with the scripted agent, and cleaned up the reviewer-facing docs. Could not re-verify IMP-002's at-the-time note that 5 tests failed on the old guard, so the record now says so. |
| 2026-11-13 | M6 | Drafted `docs/DESIGN.md`, `docs/INCIDENT.md`, the evidence index and `improvements/IMP-002.md` (the fix was committed without a record); checked every score claim against the evidence files and commit timestamps; ran tests, Ruff and a secrets/ignored-files check. |
| 2026-11-13 | M4.4c | Implemented IMP-003 steps 2 and 3 with tests (multi-option offers; wait for the caller before escalating after a failed action), after diagnoses of runs `062135Z` and `063300Z`; the step-3 fix (guidance wording, rules and constraints) was specified by the owner. |
| 2026-11-13 | M4.4c | Implemented IMP-003 (prompt consent section) and IMP-004 (escalation created/already-requested outcome, replay-first order, unique-index race handling, ledger record IDs, `ledger_matches_ehr`) with 11 tests. Rewrote its own first draft of the prompt, which quoted E6's exact caller line, to a general rule so the evaluation is not overfitted (now tested). |
| 2026-11-13 | M4.4b | Implemented IMP-002 (action vs state claims, EHR observations in the ledger, single-record evidence rule, grader split, two prompt lines) and 13 tests; ran the new tests against the committed guard to show they detect the old false positives. |
| 2026-11-13 | M4.4a | Added action-authorisation and E2 consistency checks, internal trace events, guard-rejection counts and sanitised evidence output, with tests. Owner corrected the AI design twice: escalations must be authorised too (not excluded as harmless), and generic ledger/record checks must wait for record IDs (IMP-004). |
| 2026-11-12 | M3 | Wrote the evaluation harness (scenarios, runner, grading, traces, failure reports, regression gate) and 16 tests. A harness test caught an AI bug in the E1 expectation (exact count reported a missing booking as a duplicate); fixed before any real run. |
| 2026-11-12 | M2 | Wrote the Gemini-backed agent: tools, claim guard, loop, chat CLI, demo seed and 36 fake-model tests. Mutation checks showed the retry-after-transient-timeout path was untested (read-back alone hid it); added two tests that now catch it. |
| 2026-11-12 | M1c | Wrote idempotent booking/escalation, fault injection and version-checked cancel/reschedule, and 22 tests. Found that nested `with conn:` blocks commit early in Python's sqlite3, so moved transaction ownership from repository writes to the service. Checked by mutation that the retry tests depend on the idempotency lookup. |
| 2026-11-12 | M1b | Wrote EHR operations (identity resolution, patient creation, booking, cancellation, atomic rescheduling) and 35 tests. Chose Python-side `casefold()` name matching after noting SQLite's `lower()` only folds ASCII. |
| 2026-11-12 | M0 review | Reviewed its own M0 code on request; found secret-leak paths via an empirical probe (retained exception context, construction and assignment errors), duplicated version, missing real-process exit-code test, unpinned Ruff. |

## Where AI was wrong and tests caught it

| Date | AI claim | What the test showed | Resolution |
|---|---|---|---|
| 2026-11-12 | M2: the `verify_identity` tool accepted only ISO dates of birth (`date.fromisoformat`), and the fake-model tests only ever sent ISO. | The owner's first real Gemini run (Maria calling from Luis's phone, "14 March 1985") could not verify her. Probing the real dispatcher showed every non-ISO DOB returned INVALID_ARGUMENT; the EHR lookup was correct. | The tool boundary now accepts unambiguous forms (ISO, month as a word) and still rejects all-numeric dates; regression tests added, confirmed to fail on the old parser. |
| 2026-11-12 | M2: the tool result envelope always included `verified` (default false), on reads and identity checks too, while the prompt said to claim things only when `verified=true`. | Real Gemini diagnostics (owner): `verify_identity` matched Maria but returned `verified: false`, and Gemini said no record was found. The fake-model tests never read that field on identity results. | `verified`/`action_id` only on write results; `identity_status` on every identity result; prompt states both; regression tests confirmed to fail on the old envelope. |
| 2026-11-12 | In the M0 review, AI claimed Pydantic's `hide_input_in_errors=True` would also stop frozen-assignment errors echoing the value. | The new assignment test failed: Pydantic 2.14 builds the frozen-instance error in Python without `hide_input`. | `LLMSettings.__setattr__` raises `TypeError("LLMSettings is immutable")`, which never includes the attempted value. (An intermediate version rebuilt a `ValidationError` with `hide_input=True`; the owner simplified it.) |

| 2026-11-12 / 13 | M2: the claim guard treated any cancellation wording as "the agent cancelled it". | Not caught by tests: the owner's real run `20261112T181154Z` showed the guard rejecting true "already cancelled" replies in E4 and E5; in E5 the model then booked an appointment nobody asked for. | IMP-002 (action vs state claims), 13 tests; IMP-003 for the booking. |
| 2026-11-13 | IMP-003 steps 1 and 2: AI-written prompt rules that passed every deterministic test. | Real-Gemini runs: `062135Z` (E5 and E6 still escalated without acceptance) and `063300Z` (E6 escalated in the turn of a failed retry). Fake-model tests can only show the rule is in the prompt, not that the model follows it. | Step 3 changed the failed-write guidance the model sees at that moment; E6 then passed (`063830Z`, `064320Z`). |

## Where human judgment overrode AI

| Date | AI proposal | Human decision | Reason |
|---|---|---|---|
| 2026-11-12 | LLM-driven patient simulator, LLM judge for claim extraction, 3 trials per scenario | Scripted patient simulator, no LLM judge, single trial initially | Determinism and cost; keep grading explainable |
| 2026-11-12 | ~12 scenarios | 8–10 scenarios | Focus on core failure modes within the time budget |
| 2026-11-12 | LLM drafts improvement records | Failure reports automatic; improvement records written by a human; no automatic code changes | Human accountability for changes |
| 2026-11-12 | Fingerprint of (call, operation, args) decides retry vs. new intention | Unique `action_id` per logical operation, reused across retries; fingerprint only rejects key reuse with different arguments | Guessing intent from arguments can merge a genuine repeat request with an earlier one |
| 2026-11-12 | Claim guard as structured check plus keyword backstop | Confirmed: structured ledger outcomes are primary; keywords are not relied on | Keyword matching is brittle |
| 2026-11-12 | uv + mypy; Python 3.14 floor | pip + pytest + Ruff only; `requires-python >= 3.12` | Fewer tools; portability for reviewers |
| 2026-11-12 | M1b identity lookup treated a unique phone match (no name/DOB) as a matched patient | Phone is only a hint; identity requires first name, last name and DOB; missing details return `verification_required` (ADR-019) | Caller ID can belong to someone else (F3) or be spoofed |
| 2026-11-12 | Small custom `.env` reader | Removed; read environment variables directly (`python-dotenv` later if needed) | Avoid unnecessary code |
| 2026-11-12 | PowerShell commands in docs | Windows CMD commands | Developer's actual shell |
| 2026-11-13 | IMP-003 step 3, after run `063300Z` (who first diagnosed that run is not recorded) | Owner specified the fix: the failed-write guidance says to offer a callback and wait, never escalate in the turn of a failed action; prompt and evaluator only, no runtime enforcement, no scenario wording | The model acts on the tool result it has just read; a prompt rule alone had failed twice |
| 2026-11-13 | E6 interpretation (M4.4 review question: does "Yes, cancel it." accept an offered callback?) | Owner: it does not (ADR-020); the scenario script is kept as committed, not reworded after seeing failures | Changing the test to match the model would hide the defect |
| 2026-11-13 | M4.4a check design | Owner required escalations to be graded by `actions_authorised` too, and generic ledger/record checks to wait for record IDs (IMP-004) | An unrequested escalation is still an unauthorised action |
| 2026-11-13 | Reporting final results | Owner required the final verification to be reported as split across runs (free-tier 429s on E3 and E6), not as one 6/6 run, and no score movement claimed without a recorded before/after | Honest evidence over a clean-looking number |
