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
| 2026-11-12 | M0 review | Reviewed its own M0 code on request; found secret-leak paths via an empirical probe (retained exception context, construction and assignment errors), duplicated version, missing real-process exit-code test, unpinned Ruff. |

## Where AI was wrong and tests caught it

| Date | AI claim | What the test showed | Resolution |
|---|---|---|---|
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
| 2026-11-12 | Small custom `.env` reader | Removed; read environment variables directly (`python-dotenv` later if needed) | Avoid unnecessary code |
| 2026-11-12 | PowerShell commands in docs | Windows CMD commands | Developer's actual shell |
