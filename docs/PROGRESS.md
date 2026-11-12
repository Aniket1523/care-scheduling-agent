# Progress & Time Tracking

Target: **8–9 hours** of implementation (assignment states 6–8 h).
Actual times are recorded by the product owner (wall-clock is not measurable from inside the tooling).

## Time log

| Phase | Estimate | Actual | Status | Notes |
|---|---|---|---|---|
| Analysis & design (pre-M0) | — | _TBD_ | Done | ANALYSIS.md, DECISIONS.md approved with modifications |
| M0 Project skeleton | 0.5 h | | Done | Committed `50fc0b3` |
| M1 Mock EHR | 1.5 h | | In progress | M1a `8da4eb8`, M1b `291edfa` committed; M1c (reliability) awaiting review: 113 tests pass; Ruff clean |
| M2 Tool layer | 1.5 h | | Not started | |
| M3 Agent + CLI + traces (tag `v0-baseline`) | 1.75 h | | Not started | ADR-006 provider decision needed first |
| M4 Eval harness | 1.75 h | | Not started | |
| M5 Improvement loop (tag `v1`) | 1 h | | Not started | |
| M6 Documentation & submission | 0.75 h | | Not started | |
| **Total** | **8.75 h** | | | |

## Milestone checklist

### M0 — Project skeleton
- [x] `pyproject.toml` (package metadata, deps, Ruff + pytest config; `requires-python >= 3.12`)
- [x] `src/care_agent/` package with `__main__`, CLI stub (`chat`, `eval`), env-based config
- [x] `.env.example`, `.gitignore` additions
- [x] Smoke + config tests passing (26/26); Ruff check + format clean
- [x] Pre-commit review fixes: secret-safe errors (construction, assignment, no retained context),
      single-source version, real-process CLI exit-code test, Ruff pinned to 0.17.4
- [x] `docs/AI_USAGE.md` started
- [x] Test results reported
- [x] Owner review; commit

### M1 — Mock EHR
- [x] M1a: typed IDs; Patient/Appointment models; SQLite schema (patients, phones, providers,
      services, slots, appointments) with FKs, CHECKs and one-booking-per-slot index;
      repository (insert/get patient, insert/get appointment, list by patient); 24 tests
- [x] M1b: identity verified by name + DOB with phone as a hint only (ADR-019;
      `verification_required` when details are missing; ambiguous stays ambiguous), explicit
      patient creation with duplicate check, book, cancel, atomic reschedule; `EHRError` codes;
      injected clock (`now` argument); 41 service tests
- [x] M1c: caller-provided `action_id` idempotency for booking and escalation (recorded in the
      same transaction; replay returns the original; different arguments -> IDEMPOTENCY_CONFLICT);
      escalation table + creation (one open per call); `FaultPlan` with timeout_before_commit,
      timeout_after_commit, error_after_commit; `expected_version` on cancel/reschedule checked
      inside the UPDATE (STALE_VERSION); repository writes now caller-transactional; 22 tests
- [x] Out-of-band changes: tests make them by calling the service directly on the same database
- [ ] Audit log table with call_id/action_id (deferred; JSONL traces may be enough)
- [ ] Seed data module (tests currently seed reference data with plain SQL)

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
