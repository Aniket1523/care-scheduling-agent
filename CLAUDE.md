# CLAUDE.md — Care Scheduling Agent

## Project context

Take-home for 2care.ai (Software Engineer, Voice AI): a patient-appointment scheduling agent that
**proves its own work**. Three parts:

1. A genuine LLM tool-calling agent (text CLI) that books, cancels and reschedules.
2. An in-process mock EHR (SQLite) that can time out and return an error after creating a record.
3. An evaluation harness + human-reviewed improvement loop with a regression gate.

The assignment PDF in `docs/` is the source of truth (git-ignored). Approved design:
`docs/design/ANALYSIS.md`; decisions: `docs/design/DECISIONS.md`; status/time: `docs/PROGRESS.md`.

The core invariant: **the agent never tells a patient something happened unless the backend shows it.**

## Roles

- Product owner / technical decision-maker: the user.
- Claude: primary implementation engineer.

## Working rules

1. Design before implementation.
2. One milestone at a time. Never start the next milestone without reporting the current milestone's test results and getting approval.
3. Per milestone: objective → files → approach → failure cases → **approval** → implement → run tests → report results → outstanding issues → suggested commit message.
4. Write tests alongside implementation; run relevant tests after every meaningful change.
5. Never claim something works without test evidence.
6. Never weaken or remove a test to manufacture a passing result.
7. Never deliberately disable a capability to create an evaluation failure (the commit history is audited).
8. Never hardcode secrets or commit API keys. All LLM config comes from environment variables.
9. Avoid unnecessary dependencies and abstractions; keep every line explainable.
10. Prefer deterministic automated tests (scripted fake LLM, scripted patient, injected clock, fresh temp DB).
11. Preserve meaningful Git history; no squashing. Commit only when the user asks.
12. No architectural change without explanation and approval — record approved changes in `DECISIONS.md`.
13. Do not silently omit assignment requirements or invent ones that contradict it.
14. Keep `docs/PROGRESS.md` (checklist) and `docs/AI_USAGE.md` (where AI helped / where judgment overrode it) current.

## Stack

- Python 3.14 in the existing `.venv` (Windows). Dependencies in `pyproject.toml`.
- Runtime: Pydantic; one LLM provider SDK (chosen at M3, ADR-006).
- Dev: pytest, Ruff. No uv, no mypy, no ORM, no agent framework, no FastAPI.

## Commands (Windows / PowerShell)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"   # install
.\.venv\Scripts\python.exe -m pytest                     # tests
.\.venv\Scripts\python.exe -m ruff check .               # lint
.\.venv\Scripts\python.exe -m ruff format --check .      # format check
.\.venv\Scripts\python.exe -m care_agent chat --phone <caller-phone>   # agent (M3+)
.\.venv\Scripts\python.exe -m care_agent eval            # eval loop (M4+)
```

## Engineering conventions

- Typed ID prefixes: `pat_ prv_ svc_ slot_ apt_ esc_ act_`; Pydantic rejects wrong prefixes.
- `patient_id` comes from the verified session, never from the LLM.
- Writes: tool layer mints `action_id` per logical operation; idempotency key reused across retries (ADR-009).
- Every write is verified by read-back; outcomes go to the per-call `OutcomeLedger`.
- Patient replies go through `reply_to_patient(message, confirmed_action_ids)`; the claim guard checks
  them against the ledger (ADR-011).
- Tools return the `ToolResult` envelope (`ok | failed | unknown_outcome`, `verified`, `error.code`).
- Every trace event and EHR audit row carries `call_id`.
- Timestamps come from an injected clock; SQLite files live in a system temp dir, not in OneDrive.
- Evaluation grading is deterministic (backend state, trace, structured claims). No LLM judge without approval.

## Layout (planned)

```
src/care_agent/   config, cli, ehr/, tools/, agent/, evals/
tests/            pytest suites per package
evals/            scenarios/*.json, baseline.json
improvements/     IMP-NNN.md (human-written)
runs/             eval outputs + traces (git-ignored)
docs/             design/, PROGRESS.md, AI_USAGE.md, DESIGN.md, INCIDENT.md, RUBRIC.md
```
