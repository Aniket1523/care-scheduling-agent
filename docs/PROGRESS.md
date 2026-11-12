# Progress & Time Tracking

Target: **8–9 hours** of implementation (assignment states 6–8 h).
Actual times are recorded by the product owner (wall-clock is not measurable from inside the tooling).

## Time log

| Phase | Estimate | Actual | Status | Notes |
|---|---|---|---|---|
| Analysis & design (pre-M0) | — | _TBD_ | Done | ANALYSIS.md, DECISIONS.md approved with modifications |
| M0 Project skeleton | 0.5 h | | Done | Committed `50fc0b3` |
| M1 Mock EHR | 1.5 h | | In progress | M1a `8da4eb8`, M1b `291edfa` committed; M1c (reliability) awaiting review: 113 tests pass; Ruff clean |
| M2 Agent: tools + loop + Gemini + CLI (planned M2 + M3) | 3.25 h | | Awaiting review | 150 tests pass; Ruff clean; needs a real Gemini run |
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

### M2 — Agent (owner's M2 = planned M2 tool layer + M3 agent)
- [x] ADR-006: Gemini via google-genai; manual tool dispatch, automatic function calling disabled
- [x] Tools: verify_identity, register_patient (only after NOT_FOUND for the same details),
      list_services, find_slots, list_my_appointments, book, cancel, reschedule, escalate_to_staff
- [x] Scoping in code: caller phone from session; no patient_id in any tool; ownership checks
- [x] Writes: action_id per logical operation, retried with the same ID, reconciled and verified by
      a fresh EHR read; ToolResult envelope; OutcomeLedger
- [x] Structured claim guard (ADR-011) with ledger-rendered confirmations and a narrow wording backstop
- [x] Conversation loop (bounded), deterministic ledger-based fallback reply
- [x] `chat` CLI with deterministic demo seed data; clear configuration error without a key
- [x] 36 new tests with a scripted fake model (no network); mutation-checked
- [x] Fix from the first real Gemini run: non-ISO dates of birth were rejected at the tool
      boundary, so F3 (Maria on Luis's phone) failed; unambiguous formats now accepted
- [ ] Manual conversation with a real Gemini key (owner) - re-check after the DOB fix
- [x] Temporary opt-in tool-call diagnostics (`CARE_AGENT_DEBUG_TOOLS=1`, stderr) for the real-run F3 check
- [x] Fix from real Gemini diagnostics: identity results carried `verified: false`; contract clarified
      (`identity_status` for identity, `verified` only on writes)
- [ ] JSONL traces (deferred to the evaluation milestone)
- [ ] Tag `v0-baseline` after the real-model check

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
