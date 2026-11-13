# AI Usage Log

The assignment asks where AI helped and where human judgment overrode it. Entries are added as work
happens, not reconstructed at the end.

Tool: Claude Code (Claude Opus 5.5) as the primary implementation engineer; the product owner / tech
lead reviews and approves every milestone.

## Where AI helped

| Date | Milestone | What AI did |
|---|---|---|
| 2026-11-12 | Design | Read the assignment; produced requirements breakdown, traceability matrix, domain model, schema, tool contracts, evaluation and improvement-loop design, risks and milestone plan (`docs/design/ANALYSIS.md`). |
| 2026-11-12 | Design | Drafted decision records (`docs/design/DECISIONS.md`), progress tracker and `CLAUDE.md`. |
| 2026-11-12 | M0 | Wrote the project skeleton: `pyproject.toml`, env-based config module, CLI placeholders, pytest tests, Ruff config. |
| 2026-11-12 | M1a | Wrote typed IDs, Patient/Appointment models, SQLite schema and repository, and 24 tests. Self-review caught two test problems before reporting: an import that only worked under `python -m pytest`, and a "rollback" test that could not fail; the latter was rewritten and checked with a deliberate autocommit mutation. |
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
