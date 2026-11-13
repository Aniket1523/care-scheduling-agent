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

- `requires-python >= 3.12`; developed on Python 3.14.10 in the existing `.venv` (Windows).
- Dependencies in `pyproject.toml`.
- Runtime: Pydantic; google-genai (Gemini is the only provider, ADR-006).
- Dev: pytest, Ruff. No uv, no mypy, no ORM, no agent framework, no FastAPI, no `.env` loader.
- Configuration is read directly from environment variables (see `.env.example` for names).

## Commands (Windows CMD)

The developer uses **Windows CMD**. Documented commands must use CMD syntax
(`set VAR=value`, backslash paths, `.venv\Scripts\activate.bat`).

```bat
.venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
set LLM_API_KEY=...
python -m care_agent chat --phone +15550100001
python -m care_agent eval
```

(`eval` needs `LLM_API_KEY`; exit 0 ok, 1 regression, 2 could not run. See docs/EVALUATION.md.)

## Engineering conventions

- Typed ID prefixes: `pat_ prv_ svc_ slot_ apt_ esc_ act_`; Pydantic rejects wrong prefixes.
- `patient_id` comes from the verified session, never from the LLM.
- Writes: one `action_id` per logical operation, reused across retries, new one for a new intention.
  The request fingerprint only rejects key reuse with different arguments — never classifies intent (ADR-009).
- Every write is verified by read-back; outcomes go to the per-call `OutcomeLedger`.
- Patient replies go through `reply_to_patient(message, confirmed_action_ids)`; the claim guard checks
  them against the ledger (ADR-011).
- Tools return the `ToolResult` envelope (`status`, `data`, `error.code`). `action_id` and `verified`
  appear only on write results (verified = a fresh EHR read confirmed the change); `verify_identity`
  reports `identity_status` instead.
- Each conversation has a `call_id` (session state; escalations store it). Eval trace events carry
  `run_id` and `scenario_id`, not `call_id`. There is no EHR audit table, and the `chat` CLI does not
  persist traces.
- Timestamps come from an injected clock; SQLite files live in a system temp dir, not in OneDrive.
- Evaluation grading is deterministic (backend state, trace, structured claims). No LLM judge without approval.

## Layout (as built)

```
src/care_agent/   config, cli, chat, ehr/, agent/ (tools, loop, guard, prompt, state), evals/
tests/            pytest suites per package
evals/            baseline.json, evidence/ (scenarios live in src/care_agent/evals/scenarios.py)
improvements/     IMP-NNN.md (human-reviewed; drafted with Claude Code)
manual-tests/     manual real-model test records
runs/             eval outputs + traces (git-ignored)
docs/             design/, PROGRESS.md, AI_USAGE.md, DESIGN.md, INCIDENT.md, EVALUATION.md
```

The rubric and its blind spots are in `docs/EVALUATION.md`; there is no separate RUBRIC.md.
