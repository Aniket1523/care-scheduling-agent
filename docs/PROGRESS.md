# Progress & Time Tracking

Target: **8–9 hours** of implementation (assignment states 6–8 h).
Actual times are recorded by the product owner (wall-clock is not measurable from inside the tooling).

## Time log

| Phase | Estimate | Actual | Status | Notes |
|---|---|---|---|---|
| Analysis & design (pre-M0) | — | _TBD_ | Done | ANALYSIS.md, DECISIONS.md approved with modifications |
| M0 Project skeleton | 0.5 h | | Not started | |
| M1 Mock EHR | 1.5 h | | Not started | |
| M2 Tool layer | 1.5 h | | Not started | |
| M3 Agent + CLI + traces (tag `v0-baseline`) | 1.75 h | | Not started | ADR-006 provider decision needed first |
| M4 Eval harness | 1.75 h | | Not started | |
| M5 Improvement loop (tag `v1`) | 1 h | | Not started | |
| M6 Documentation & submission | 0.75 h | | Not started | |
| **Total** | **8.75 h** | | | |

## Milestone checklist

### M0 — Project skeleton
- [ ] `pyproject.toml` (package metadata, deps, Ruff + pytest config)
- [ ] `src/care_agent/` package with `__main__`, CLI stub (`chat`, `eval`), env-based config
- [ ] `.env.example`, `.gitignore` additions
- [ ] Smoke + config tests passing; Ruff clean
- [ ] `docs/AI_USAGE.md` started
- [ ] Test results reported; commit

### M1 — Mock EHR
- [ ] Schema with constraints (partial unique indexes, CHECKs, FKs)
- [ ] Seed data + injected clock
- [ ] Service: patients, slots, book, cancel, atomic reschedule, escalate
- [ ] Idempotency records (same transaction as write; key reuse with different hash rejected)
- [ ] `FaultPlan`: timeout_before_commit, timeout_after_commit, error_after_commit
- [ ] Optimistic concurrency (`expected_version`)
- [ ] Out-of-band mutation hooks; audit log with call_id/action_id
- [ ] Tests for every invariant and fault mode

### M2 — Tool layer
- [ ] Typed IDs + Pydantic argument models
- [ ] Scoping guards (verified patient, ownership, register-only-after-search)
- [ ] action_id / fingerprint / idempotency rules (ADR-009)
- [ ] Retry, reconcile, read-after-write verification
- [ ] `ToolResult` envelope; OutcomeLedger updates
- [ ] Tests incl. every fault mode

### M3 — Agent (tag `v0-baseline`)
- [ ] ADR-006 decided (provider adapter)
- [ ] `LLMClient` protocol, provider adapter, `ScriptedLLM`
- [ ] System prompt; ConversationState; agent loop
- [ ] Structured claim guard (ADR-011)
- [ ] `chat` CLI; JSONL traces
- [ ] Tests with ScriptedLLM; manual conversation check

### M4 — Evaluation harness
- [ ] Scenario JSON schema; 8–10 scenarios
- [ ] Scripted patient simulator
- [ ] Graders: state, trace, claim, outcome; gating
- [ ] Runner, scoring, results.json, failures.json
- [ ] Baseline + regression exit code
- [ ] Harness tests

### M5 — Improvement loop (tag `v1`)
- [ ] Baseline run recorded (genuine results)
- [ ] IMP record(s) written and reviewed
- [ ] Fix commits; re-run shows score movement with no regression

### M6 — Submission
- [ ] README with exactly one agent command and one eval command
- [ ] `docs/DESIGN.md` (≤1 page, before/after scores, one real-clinic change)
- [ ] `docs/INCIDENT.md` (≤½ page, uses our traces)
- [ ] `docs/RUBRIC.md` incl. blind spots
- [ ] `docs/AI_USAGE.md` complete; total time recorded
- [ ] Screen recording (owner)
