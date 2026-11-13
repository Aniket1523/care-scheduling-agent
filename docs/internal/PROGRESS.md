# Progress & Time Tracking

Target: **8–9 hours** of implementation (assignment states 6–8 h).
Actual times are recorded by the product owner. They cannot be measured from inside the tooling,
and the commit history (first commit 2026-11-12 17:03 +0530, last 2026-11-13 12:08 +0530) spans an
overnight break, so it does not establish time spent.

**Total time spent: `<<OWNER: fill in, e.g. "about N hours">>`**

## Time log

| Phase | Estimate | Actual | Status | Notes |
|---|---|---|---|---|
| Analysis & design (pre-M0) | — | _TBD_ | Done | ANALYSIS.md, DECISIONS.md approved with modifications |
| M0 Project skeleton | 0.5 h | | Done | Committed `50fc0b3` |
| M1 Mock EHR | 1.5 h | | Done | M1a `8da4eb8`, M1b `291edfa`, M1c `0b9276c` |
| M2 Agent: tools + loop + Gemini + CLI (planned M2 + M3) | 3.25 h | | Done | `7582822` (includes the IMP-001 fix) |
| M3 Eval harness + real Gemini baseline (planned M4) | 1.75 h | | Done | `2143a0b`; baseline 6/6 under the M3 checks |
| M4 Improvement loop: IMP-001 to IMP-004 (planned M5) | 1 h | | Done | `9cf313b` to `113367f`; 230 tests pass; Ruff clean |
| M6 Documentation & submission | 0.75 h | | Docs done; recording and time pending (owner) | DESIGN, INCIDENT, final evidence |
| **Total** | **8.75 h** | `<<OWNER>>` | | |

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
- [x] Manual conversation with a real Gemini key (owner): IMP-001 retest and
      `manual-tests/2026-11-12-reschedule.md`
- [x] Temporary opt-in tool-call diagnostics (`CARE_AGENT_DEBUG_TOOLS=1`, stderr) for the real-run F3 check
- [x] Fix from real Gemini diagnostics: identity results carried `verified: false`; contract clarified
      (`identity_status` for identity, `verified` only on writes)
- [x] JSONL traces (built in the evaluation harness; the chat CLI does not persist traces)
- [ ] Tag `v0-baseline` (not created; see below)

### M3 — Evaluation harness and improvement loop (owner numbering)
- [x] Scenarios E1-E6 (F1-F5 + cancellation that never commits), explicit EHR expectations
- [x] Runner: fresh seeded DB, fixed clock, scripted caller, real agent code, model-call count
- [x] Deterministic grading from EHR state + `claims_match_ehr`; no LLM judge
- [x] JSONL traces, results.json, failures.json (findings, likely cause, fix layer)
- [x] Baseline + regression gate (exit 1), `--scenario`, `--update-baseline` (refused on regression)
- [x] `python -m care_agent eval`; docs/EVALUATION.md; improvements/TEMPLATE.md
- [x] 16 network-free harness tests (every scenario passes with a well-behaved scripted agent;
      failures, regressions, model errors, traces)
- [x] Honest baseline with real Gemini: 6/6 (run `20261112T160955Z`, `evals/baseline.json`),
      recorded after the IMP-001 fix, under the M3 checks (offline regrade under the later M4.4a
      checks: 5/6, E6)
- [x] IMP records for genuine failures: IMP-001 (see M4 below)

### M4 — Improvement loop (owner numbering)
- [x] M4.1 IMP-001: identity result carried `verified: false`; Gemini told a verified caller no
      record existed. Before = manual real-Gemini session; after = real-Gemini retest, E3 run
      `20261112T155834Z`, 6/6 baseline. No measured 0/6 -> 6/6 is claimed (baseline came after)
- [x] M4.2 Manual real-Gemini reschedule test recorded: `manual-tests/2026-11-12-reschedule.md`
      (Maria, `apt_mariacheckup` -> Tue 17 Nov 09:00 Dr Lee, `verified: true`, guard accepted)
- [x] M4.3 IMP-001 reviewed against code (one inaccuracy fixed: `not_checked` is not set via
      `_identity_failed()`; non-ASCII arrows replaced for cp1252 viewers)
- [x] M4.3 Focused IMP-001 tests: 7 passed; full suite: 189 passed; Ruff lint/format clean
- [x] M4.3 Regression gate: controlled run on a temp copy of the committed baseline with E1
      deliberately failing -> exit 1, REGRESSION: E1, baseline update refused, committed
      baseline unchanged
- [x] M4.3 Real-Gemini eval re-run against the baseline: owner run `20261112T181154Z` passed 6/6
      (under the M3 checks); its review found the issues addressed in M4.4
- [x] M4.4a Evaluation harness: `actions_authorised` (incl. escalations, attempt limits, E6
      decision per ADR-020), E2 `escalation_actions_match_records`, trace events
      (`fault_injected`, `tool_attempt`, `reconcile_read`; never sent to the model), claim-guard
      rejection counts, `--record-evidence` (`evals/evidence/`). No prompt or agent behaviour change.
      Scripted E2 is a strict xfail until IMP-004 (the tool still writes on a repeat request)
- [x] M4.4a Owner: real run `python -m care_agent eval --record-evidence` = the "before"
      (expected exit 1 against the old baseline; do not update the baseline). Offline regrade of
      older traces under these checks: `181154Z` 3/6 (E2, E5, E6), `160955Z` 5/6 (E6)
- [x] M4.4a owner run `20261113T053628Z` (evidence recorded): E2 and E6 fail under the new checks;
      E4 and E5 errored with 429 RESOURCE_EXHAUSTED, so it is not a complete before-score
- [x] M4.4b IMP-002 claim guard: verified actions (with `record_id`) vs fresh EHR observations;
      first-person claims need a verified action, state claims may use a cancelled observation,
      evidence must point to one record; grader `claims_match_ehr` split the same way; prompt asks
      to re-list action IDs and never claim a cancellation the agent did not make. 13 new tests;
      5 of the new guard tests fail on the committed guard (checked)
- [x] M4.4c IMP-003 (`improvements/IMP-003.md`): prompt Consent section per ADR-020 (explicit
      requests authorise; offers need clear acceptance; ambiguous answers are clarified; no
      scenario wording quoted)
- [x] M4.4c IMP-004 (`improvements/IMP-004.md`): `create_escalation` returns created /
      already-requested (replay first, then open check, then insert; only the
      one-open-escalation unique-index violation maps to already-requested); the tool reports
      `already_requested` with no action; ledger `record_id` for escalations; generic
      `ledger_matches_ehr` check; scripted E2 passes (strict xfail removed). 228 tests pass
- [x] M4.4c IMP-003 step 2 (`228481a`, after run `062135Z`): one alternative at a time; a bare
      "yes" to several offers chooses none; a "yes" that restates the request does not accept a callback
- [x] M4.4c IMP-003 step 3 (`113367f`, after run `063300Z`): failed-write guidance and prompt say to
      offer a callback and wait for the answer; never escalate in the turn of the failed action
- [x] IMP-002 record written at submission (`improvements/IMP-002.md`) from the commit and trace
- [x] Final real-Gemini evidence on `113367f` (all `gemini-3.5-flash-lite`): full run `063923Z`
      E1 E2 E4 E5 pass, E3 E6 errored (429 free-tier quota); re-run alone: E3 `064153Z` pass,
      E6 `064320Z` pass (also `063830Z`). All six passed individually; **not one clean 6/6 run**.
      Index: `evals/evidence/README.md`
- [x] Baseline not updated: `evals/baseline.json` (6/6 pass, run `160955Z`) already records all six
      as pass, and `--update-baseline` from split runs would add nothing

### Original plan items not built (superseded or descoped)
- Scenario JSON files and 8–10 scenarios: scenarios are Python (`src/care_agent/evals/scenarios.py`), six of them
- Tags `v0-baseline` / `v1`: not created; commits and evidence files carry the history
- Audit log table and seed-data module (M1): deferred; see INCIDENT.md "Honest gap"

### M6 — Submission
- [x] README with one agent command and one eval command (checked on Windows: both exit with a
      clear configuration error when `LLM_API_KEY` is unset)
- [x] `docs/DESIGN.md` (≤1 page, before/after scores with the split final run disclosed, one
      real-clinic change)
- [x] `docs/INCIDENT.md` (≤½ page, uses the E6 trace `064320Z`)
- [x] Rubric and blind spots: in `docs/EVALUATION.md` ("Why grading reads the EHR, not the
      transcript" and "Known limits"); no separate RUBRIC.md
- [x] `docs/AI_USAGE.md` complete
- [x] Final checks at `8f2852a`: 230 tests pass; Ruff check and format clean; no secrets or `.env` tracked
- [x] M6 final tasks: E6 `checkup_unchanged` proven able to fail (`3d05253`); rate-limit pacing
      and backoff, persistent 429 graded `error` (`8692e8f`); `--rebuild-baseline` from one complete
      run, original baseline copied to `evals/baseline-history/` (`464a98d`); verified before/fix
      commit pairs in `evals/evidence/README.md` (`3413af8`); reviewer-facing cleanup, internal docs
      moved to `docs/internal/` (`c0f6a89`). 244 tests pass; Ruff clean. The baseline itself is
      unchanged; the rebuild command is for the owner to run.
- [ ] Optional: one more full real-Gemini run for a single 6/6 record. Not attempted during
      finalisation: no `LLM_API_KEY` was available in that environment. The split-run disclosure
      stands.
- [ ] Total time recorded (owner; placeholder above)
- [ ] Screen recording (owner)
