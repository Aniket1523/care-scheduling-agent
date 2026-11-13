# Care Scheduling Agent — Requirements Analysis & Approved Architecture

> **This is the pre-build analysis and plan (2026-11-12), kept unchanged as a record.** It describes
> what was planned, not what was built. The as-built system is in `docs/DESIGN.md`,
> `docs/EVALUATION.md` and `docs/design/DECISIONS.md` (ADRs override this document).
>
> Planned here but **not built**: the `audit_log` table (the EHR has no audit table; traces are
> written only by the eval runner), `docs/RUBRIC.md` (rubric and blind spots are in
> `docs/EVALUATION.md`), scenario JSON files and 8–10 scenarios (six scenarios, in Python), the
> `v0-baseline` / `v1` tags, and the `harness_error` failure category (model API errors are
> reported as status `error`; the other categories exist as hints in `failures.json`). Changed during the build: identity is verified by name and date of
> birth, with the phone number only a hint (ADR-019), not caller ID first; consent follows
> ADR-020.

Status: **Approved** (with product-owner / tech-lead modifications, see `DECISIONS.md`)
Source of truth: `docs/Take-Home_ Software Engineer, Voice AI (v3).pdf` (not committed; `docs/*.pdf` is git-ignored)
Last updated: 2026-11-12

---

## 1. The assignment in one paragraph

Build a patient-appointment scheduling agent (multi-turn, tool-using, text is fine), a small mock EHR it
calls through its tools (which can be made to time out and to return an error *after* creating a record),
and an evaluation harness that scores the agent on designed scenarios — at least three of which reproduce
failures F1–F5 — and closes an improvement loop: failure → structured improvement → re-run → score moves
with no regression. One command runs the scenarios and exits non-zero if a previously passing scenario now
fails. Deliverables: runnable repo (README with one command for the agent, one for the eval loop), a screen
recording, a ≤1-page design note (with before/after scores and one change for a real clinic), a ≤½-page
answer to the written incident question, time spent, and notes on AI usage. Budget stated by the assignment:
6–8 hours; our target: **8–9 hours**.

### The failure catalogue

| ID | Failure | Root-cause class |
|---|---|---|
| F1 | Agent said "you are booked"; no appointment existed. Confirmation not checked against tool result. | Unverified claim |
| F2 | Agent said "escalated"; no record existed. Elsewhere, a retry created a second escalation. | Unverified claim + non-idempotent retry |
| F3 | Existing patient called from husband's phone; no match, no fallback. Next day a similar caller became a duplicate patient record. | Identity resolution + duplicate prevention (spans two calls) |
| F4 | Reschedule sent a service ID where the appointment ID belongs. | Untyped identifiers |
| F5 | Patient cancelled in the EHR 25 min earlier; cached state still showed the appointment; agent acted on it. | Stale state |

---

## 2. Requirement-by-requirement breakdown

| ID | Requirement | Interpretation |
|---|---|---|
| R1 | Real multi-turn conversation; book, cancel, reschedule via tools | Genuine LLM tool-calling loop with conversation state; CLI text interface |
| R2 | Small fake EHR, called via tools | In-process mock backend with real persistence and constraints |
| R3 | EHR can be made to **time out** | Fault injection: `timeout_before_commit` and `timeout_after_commit` (outcome unknown to the caller) |
| R4 | EHR can **return an error after creating a record** | Fault injection: `error_after_commit` — committed, but caller sees an error |
| R5 | Never tell the patient something happened unless the backend shows it | Read-after-write verification + OutcomeLedger + structured claim guard |
| R6 | Harness scores the agent on designed scenarios incl. hard cases | Scenario suite, rubric, scoring |
| R7 | ≥3 scenarios reproduce F1–F5 | We cover all five (§8) |
| R8 | Failure → concrete, structured improvement | Automatic structured failure reports; human-written improvement records |
| R9 | Re-run same scenarios; score moves, no regression | Before/after on identical suite |
| R10 | One command; non-zero exit if previously-passing scenario now fails | Persisted baseline + comparison |
| R11 | Fix may be prompt, tooling, retrieval, memory, timeout/retry policy | Improvement record states the layer |
| R12 | Start from best honest version; never disable a capability to manufacture a failure (commit history is checked) | Commit/tag discipline (§12) |
| R13 | Document assumptions for ambiguities | §10 + `DECISIONS.md` |
| R14 | State where a transcript-only judge is blind | Rubric "blind spots" section |
| R15 | Written question answered from *our own* logs/traces | Traces + EHR audit log share `call_id` |
| R16 | README: one command to run the agent, one to run the eval loop | `python -m care_agent chat …`, `python -m care_agent eval` |
| R17 | Screen recording of conversation + loop | Repo supports it via `v0-baseline` / `v1` tags |
| R18 | Design note ≤1 page incl. before/after scores, one real-clinic change | `docs/DESIGN.md` |
| R19 | Time spent | `docs/internal/PROGRESS.md` |
| R20 | Where AI helped / where judgment overrode it | `docs/AI_USAGE.md`, maintained from M0 |
| R21 | Able to explain every line | Few dependencies, no frameworks |

## 3. Traceability matrix

| Req | Design element | Verified by |
|---|---|---|
| R1 | `agent/loop.py`, `ConversationState`, CLI | Unit tests with scripted fake LLM; happy-path scenarios |
| R2 | `ehr/` service + SQLite schema | EHR unit tests (constraints, transitions) |
| R3 | `FaultPlan` timeout modes | EHR fault tests; F1 scenarios, C1 |
| R4 | `FaultPlan` `error_after_commit` | EHR fault tests; F2 scenario |
| R5 | Tool-layer read-back, OutcomeLedger, structured claim guard | Tool/guard unit tests; gating `no_unverified_claims` check in every scenario |
| R6–R7 | `evals/scenarios/*.json`, graders, runner | Harness unit tests; scenario suite |
| R8 | `eval` writes `runs/<run_id>/failures.json`; `improvements/IMP-NNN.md` | Committed improvement record + linked fix commit |
| R9–R10 | `evals/baseline.json`, regression comparison, exit codes | Harness tests for exit-code logic |
| R11 | `layer` field of improvement record | Record review |
| R12 | Commit sequence, tags `v0-baseline`, `v1` | `git log` |
| R13–R14 | `DECISIONS.md`, `docs/RUBRIC.md` blind-spot section | Review |
| R15 | JSONL traces + `audit_log`, joined by `call_id` | `docs/INCIDENT.md` cites real fields |
| R16–R20 | README, DESIGN, AI_USAGE, PROGRESS | Final checklist (M6) |

## 4. Functional & non-functional requirements

**Functional**
- Identify the caller by caller-ID phone; fall back to name + DOB; register a new patient only after a
  search returned no match; ambiguous matches → escalate, never guess.
- List services; find available slots.
- Book, cancel, reschedule (reschedule is one atomic EHR operation).
- Escalate to staff, at most one open escalation per call.
- Per-operation fault injection (timeout before/after commit, error after commit).
- Out-of-band EHR mutations mid-conversation (for F5).
- Eval: run scenarios → grade → score → compare to baseline → exit code.
- Automatic structured failure reports.

**Non-functional**
- Correctness first: no unverified claims, no duplicate records, no acting on stale state.
- Idempotent writes (per logical action — §7.3).
- Deterministic test infrastructure: fresh DB per run, injected clock, scripted patient, scripted fake LLM for unit tests.
- Observability: `call_id` correlation across agent traces and EHR audit log.
- Type safety at boundaries: Pydantic models, typed ID prefixes.
- No secrets in the repo; all LLM configuration from environment variables.
- Minimal dependencies; every line explainable.

## 5. Domain model

| Entity | Fields (essential) |
|---|---|
| Patient | `pat_…`, first_name, last_name, dob, phones (via `patient_phones`) |
| Provider | `prv_…`, name |
| Service | `svc_…`, name, duration_min |
| Slot | `slot_…`, provider_id, start_at, end_at (bookable if no `booked` appointment holds it) |
| Appointment | `apt_…`, patient_id, provider_id, service_id, slot_id, start_at, end_at, status ∈ {booked, cancelled}, version, timestamps, cancel_reason |
| Escalation | `esc_…`, call_id, patient_id?, reason, status ∈ {open, closed} |
| IdempotencyRecord | key, operation, request_hash, response_json |
| AuditLog | request_id, call_id, action_id, operation, params, outcome, error_code, injected_fault, timestamp |

Agent-side:

| Object | Purpose |
|---|---|
| `ConversationState` | call_id, caller_phone, verified patient_id, identity attempts, turn count |
| `OutcomeLedger` | One entry per logical action: action_id, operation, fingerprint, status ∈ {pending, verified_success, failed, unknown}, verified backend data, attempts |

Typed ID prefixes make F4 a validation error at the tool boundary rather than a backend failure.

## 6. Architecture

```
CLI (chat) ──► Agent loop ──► LLMClient protocol ──► provider adapter (env-configured) | ScriptedLLM (tests)
                  │
                  ├─ ConversationState + OutcomeLedger
                  ├─ Claim guard (validates structured reply against the ledger)
                  ▼
            Tool layer  (Pydantic args, typed IDs, scoping guards, action_id + idempotency,
                  │      timeout/retry/reconcile policy, read-after-write verification,
                  │      ToolResult envelope)
                  ▼
            EHRClient protocol ──► EHR service (in-process) ──► SQLite (sqlite3)
                                         ▲
                                   FaultPlan + out-of-band mutation hooks (tests/evals only)

CLI (eval) ──► Runner ──► ScriptedPatient + Agent + fresh EHR ──► Graders ──► Score
                                                                      └► baseline compare ► exit code
                                                                      └► failures.json (structured)
Traces: JSONL per call (turns, tool calls, ToolResults, faults, ledger, guard decisions), keyed by call_id
```

Key choices (details and rejected alternatives in `DECISIONS.md`):
- In-process EHR, no FastAPI: same semantics (incl. "committed but client saw a timeout"), deterministic, fast.
- `sqlite3` stdlib, explicit SQL, no ORM; fresh DB file in a temp dir per run (not in OneDrive).
- Custom tool loop, no agent framework.
- `requires-python >= 3.12`, developed on Python 3.14.10 in the existing `.venv`; pip + `pyproject.toml`;
  pytest + Ruff. No uv, no mypy. Developer shell: Windows CMD.
- Configuration read directly from environment variables (no `.env` loader for now).

## 7. Contracts

### 7.1 Database schema (sketch)

```sql
patients(id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, dob TEXT, created_at TEXT)
patient_phones(patient_id TEXT REFERENCES patients(id), phone TEXT, PRIMARY KEY (patient_id, phone))
  CREATE INDEX ix_patient_phones_phone ON patient_phones(phone);
providers(id TEXT PRIMARY KEY, name TEXT)
services(id TEXT PRIMARY KEY, name TEXT, duration_min INTEGER)
slots(id TEXT PRIMARY KEY, provider_id TEXT REFERENCES providers(id), start_at TEXT, end_at TEXT)
appointments(id TEXT PRIMARY KEY, patient_id, provider_id, service_id, slot_id,
             start_at TEXT, end_at TEXT,
             status TEXT NOT NULL CHECK (status IN ('booked','cancelled')),
             version INTEGER NOT NULL DEFAULT 1,
             created_at TEXT, updated_at TEXT, cancelled_at TEXT, cancel_reason TEXT)
  CREATE UNIQUE INDEX ux_one_booking_per_slot ON appointments(slot_id) WHERE status = 'booked';
escalations(id TEXT PRIMARY KEY, call_id TEXT, patient_id TEXT, reason TEXT,
            status TEXT NOT NULL CHECK (status IN ('open','closed')), created_at TEXT)
  CREATE UNIQUE INDEX ux_one_open_escalation_per_call ON escalations(call_id) WHERE status = 'open';
idempotency_keys(key TEXT PRIMARY KEY, operation TEXT, request_hash TEXT, response_json TEXT, created_at TEXT)
audit_log(id INTEGER PRIMARY KEY, request_id TEXT, call_id TEXT, action_id TEXT, operation TEXT,
          params_json TEXT, outcome TEXT, error_code TEXT, injected_fault TEXT, created_at TEXT)
```

- `PRAGMA foreign_keys = ON`.
- A write and its idempotency record commit in **one transaction**. `*_after_commit` faults are raised after
  that commit — exactly the "error after creating a record" behaviour.
- Same idempotency key with a different request hash → `IDEMPOTENCY_KEY_REUSED` error (never silently returns a mismatched result).
- `create_patient` performs a normalised name + DOB duplicate check and returns `POSSIBLE_DUPLICATE`
  (not a hard unique constraint — real people can share name + DOB).
- `cancel`/`reschedule` accept `expected_version`; mismatch → `STALE_VERSION` (F5 backstop).
- Timestamps are ISO-8601 strings from an injected clock.

### 7.2 Agent-facing tools

`patient_id` is taken from the verified session, never from the LLM.

| Tool | Args | Guard |
|---|---|---|
| `lookup_caller` | — (uses caller-ID) | — |
| `search_patient` | first_name, last_name, dob | — |
| `register_patient` | first_name, last_name, dob | Only after `search_patient` in this call returned no match |
| `list_my_appointments` | — | Verified patient; always live read |
| `list_services` | — | — |
| `find_slots` | service_id, date_from, date_to, provider_id? | — |
| `book_appointment` | slot_id, service_id | Verified patient |
| `cancel_appointment` | appointment_id, reason | Appointment owned by verified patient; live re-read first |
| `reschedule_appointment` | appointment_id, new_slot_id | Same; atomic in EHR |
| `escalate_to_staff` | reason | One open escalation per call |
| `reply_to_patient` | message, confirmed_action_ids[] | Claim guard (§7.4) |

Every operational tool returns a `ToolResult`:

```
{ status: "ok" | "failed" | "unknown_outcome",
  verified: bool,                 # true only after read-after-write confirmed backend state
  action_id: str | null,          # for writes
  data: {...} | null,
  error: { code, message, retryable } | null,
  guidance: str | null }          # short, factual hint to the model (e.g. "do not tell the patient this succeeded")
```

### 7.3 Action identity and idempotency (modified per review)

- Every **logical operation** gets a unique **`action_id`** (`act_…`), minted by the tool layer. The EHR
  idempotency key is derived from it. The LLM never invents keys.
- **Retries reuse the `action_id`.** This covers the tool layer's internal retries (timeout /
  after-commit error) and an explicit model-level retry: a write tool accepts an optional `action_id`
  taken from a previous `ToolResult` (`unknown_outcome` or retryable failure); passing it means "this is
  the same operation, try again".
- **A new user intention gets a new `action_id`.** A write call without `action_id` is a new logical
  operation.
- **The fingerprint is a guard, not a classifier.** It is the hash of the normalised request arguments,
  stored with the idempotency key. It is used *only* to reject reuse of an existing key with different
  arguments (`IDEMPOTENCY_KEY_REUSED`). It is never used to decide whether a call is a retry or a new
  intention.
- Domain constraints are the backstop if the model starts a *new* action for what is really the same
  intention: one booking per slot, one open escalation per call (EHR partial unique indexes).
- Cross-call duplication (F3 day 2) is not an idempotency problem; it is prevented by identity resolution
  and the EHR duplicate check.

**Write path:** mint (new intention) or reuse (retry) action_id → call EHR with timeout → on timeout / after-commit error, retry with the
same key (max 2 retries) → if still unknown, **reconcile** (look up by idempotency key / natural key) →
**read back** the record → set `verified=true` only if the read-back matches → record in OutcomeLedger.
Unresolvable unknowns are reported to the model as `unknown_outcome` with guidance to tell the patient
the truth and offer escalation.

### 7.4 Claim guard (modified per review)

Primary mechanism is **structured**, not keyword-based:

1. The agent replies to the patient only via `reply_to_patient(message, confirmed_action_ids)`.
   (A plain-text model turn is treated as a reply with `confirmed_action_ids = []`.)
2. Every `confirmed_action_id` must exist in this call's OutcomeLedger with status `verified_success`;
   otherwise the reply is blocked.
3. The confirmation details the patient hears (date, time, provider, reference) are **rendered from the
   ledger's verified backend data**, appended as a canonical confirmation line — the model cannot
   hallucinate a time it was not given.
4. A lightweight success-language detector is a **secondary backstop only**: if the message reads like a
   success claim for an operation type with no matching verified confirmation, the reply is blocked.
5. On block: one corrective re-prompt carrying the ledger facts; if still invalid, a deterministic fallback
   message generated from the ledger (truthful status + offer to escalate).
6. Every guard decision is traced.

### 7.5 EHR internal API

Same operations as 7.2 plus `call_id`, `action_id`/`idempotency_key`, `expected_version`; and
`find_by_idempotency_key` for reconciliation. Test/eval-only hooks: `FaultPlan` (per-operation,
per-call-index, mode) and direct out-of-band mutations.

### 7.6 LLM configuration (modified per review)

All provider/model/API configuration is read directly from environment variables (`.env.example`
committed with names only, as documentation; no `.env` loader for now — `python-dotenv` may be added
later if needed):

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | Adapter selector |
| `LLM_MODEL` | Model name |
| `LLM_API_KEY` | API key (never logged; masked in repr) |
| `LLM_BASE_URL` | Optional endpoint override |
| `LLM_TIMEOUT_SECONDS` | Request timeout |
| `LLM_TEMPERATURE` | Default 0 |

No assumption that Claude Code access provides API access: unit tests use a `ScriptedLLM` and need no key;
the interactive agent and the eval run require a key and fail fast with a clear message if absent.
Which provider adapter is implemented first is decided at M3 (see `DECISIONS.md`, pending).

## 8. Evaluation strategy (modified per review)

- **Agent:** the genuine LLM-driven scheduling agent.
- **Patient:** a **scripted, deterministic simulator**. Each scenario defines a persona fact card (name, DOB,
  phone, appointment preferences) and an ordered script of intents. The simulator answers agent questions by
  matching a small set of question types (name, DOB, phone, time preference, confirmation, "anything else")
  and otherwise advances the script. A `max_turns` cap ends runaway conversations. If the simulator cannot
  produce an answer it records a `harness_error` (distinct from an agent failure) so the scenario is not
  mis-scored.
- **No LLM judge initially.** Grading uses:
  1. **Backend state checks** (deterministic): appointment/escalation/patient counts, statuses, no duplicates.
  2. **Trace checks** (deterministic): correct ID types; live read before mutation; no `register_patient`
     when a match existed; idempotency key reused across retries of the same action.
  3. **Claim checks** (deterministic): every `confirmed_action_id` in the transcript is `verified_success`
     *and* consistent with final backend state; secondary success-language backstop on reply text.
  4. **Task outcome:** goal achieved, or honestly reported + escalated.
- **Scoring:** weighted checks per scenario; **gating checks** (unverified claim, duplicate record) fail
  the scenario outright. Suite metrics: scenarios passed / total, mean weighted score.
- **Trials:** single trial per scenario initially (temperature 0). `--trials N` may be added later if
  flakiness is observed; flakiness is documented, not hidden.
- **Regression gate:** `evals/baseline.json` records per-scenario pass/fail. `eval` exits 1 if any
  baseline-passing scenario now fails; baseline changes only via explicit `--update-baseline`.

### Initial scenario suite (10)

| ID | Scenario | Key checks |
|---|---|---|
| S1 | Happy-path booking (caller-ID match) | 1 booked appointment; confirmation verified |
| S2 | Happy-path reschedule | Same appointment, new slot, version+1; old slot free |
| S3 | Happy-path cancel | Status cancelled; confirmation verified |
| F1-a | Booking, EHR `timeout_before_commit` on every attempt | No appointment; agent makes no booking claim; honest message/escalation |
| F1-b | Booking, `timeout_after_commit` once | Exactly 1 appointment; reconciliation; confirmation only after read-back |
| F2 | Patient asks for a human; `error_after_commit` on escalation | Exactly 1 escalation; claim verified |
| F3 | Two calls: existing patient from unknown phone (call 1), similar caller next day (call 2) | Matched by name+DOB; zero new patient records across both calls |
| F4 | Patient with two appointments asks to "move my cleaning" | Reschedule called with the correct `apt_` ID; other appointment untouched |
| F5 | Appointment cancelled out-of-band after the agent first lists it; patient then asks to reschedule | Live re-read before mutation; agent tells the truth; no mutation of a cancelled appointment |
| C1 | Cancel with `timeout_before_commit` on every attempt (mirrors the written question) | Appointment still booked; agent does **not** claim cancellation |

### Blind spots (to be expanded in `docs/RUBRIC.md`)

- A transcript-only judge cannot see whether a record exists, whether a duplicate was created, whether a
  timeout committed anyway, or whether stale data was acted on — hence backend state is our source of truth.
- Our harness is blind to: speech/ASR errors, latency, realistic patient behaviour (scripted patient is
  cooperative and narrow), real EHR semantics, and success claims phrased in ways the backstop detector
  misses when the model bypasses the structured reply.
- A single trial cannot measure rare failures.

## 9. Improvement loop (modified per review)

```
python -m care_agent eval
  ├─ runs/<run_id>/results.json      per-scenario checks, scores
  ├─ runs/<run_id>/failures.json     AUTOMATIC structured failure reports
  └─ runs/<run_id>/traces/*.jsonl
                     │
                     ▼  (human)
improvements/IMP-NNN.md   written & reviewed by a human: failure ref, taxonomy category,
                          root cause, layer (prompt|tool|policy|retry|memory|harness),
                          change, target scenarios, acceptance criteria, before/after scores
                     │
                     ▼  (human applies code change; commit "IMP-NNN: …")
python -m care_agent eval   → score delta + regression gate → --update-baseline when accepted
```

- Failure report fields: scenario_id, run_id, failed check id, taxonomy category, evidence (relevant trace
  events, ledger entries, backend state diff), suspected layer (heuristic from check type).
- Taxonomy: `unverified_claim`, `duplicate_record`, `wrong_id_type`, `stale_state`, `identity_miss`,
  `unreconciled_unknown_outcome`, `task_incomplete`, `harness_error`.
- **No automatic code modification.**

## 10. Assumptions & ambiguities

| Topic | Decision |
|---|---|
| "Backend shows it happened" | A read-after-write confirms the expected state; a write's return value alone is insufficient |
| F5 "cache" | The agent's in-conversation memory of earlier reads. Fix: live read before every mutation; EHR `expected_version` as backstop |
| Clock / timezone | Single clinic timezone; injected `now` so "Tuesday" resolves deterministically |
| Identity | Caller-ID first, then name + DOB; ambiguous → escalate |
| Escalation scope | One open escalation per `call_id` |
| Caller ID | Passed to the CLI as `--phone` |
| Reschedule | Atomic (cancel+book could fail halfway, leaving the patient with nothing) |
| Out of scope | Cancellation policy, insurance, multi-clinic, voice/telephony, frontend |
| Time budget | 8–9 h implementation target |

## 11. Major technical risks

| Risk | Mitigation |
|---|---|
| LLM nondeterminism flips scenarios → noisy regression gate | Temperature 0, deterministic graders, scripted patient; document flakes; `--trials` later if needed |
| Scripted patient is brittle to agent phrasing | Broad question-type matching; `harness_error` category; review transcripts of failures |
| v0 passes everything → nothing for the loop to fix | Honest response is harder scenarios exposing real gaps; never degrade the agent |
| Loop looks staged | Ordered, unsquashed commits: v0 → scenarios → failing run → IMP fix; tags |
| Model bypasses structured reply | Plain text treated as reply with no confirmations + backstop detector + trace check |
| API cost / key availability | Unit tests need no key; evals 10 scenarios × 1 trial |
| Windows + OneDrive SQLite locking | DB files in system temp dir; `pathlib` everywhere |
| Python 3.14 package compatibility | Verify Pydantic / provider SDK wheels at install (M0/M3) |
| Time overrun | Cut line (§12) |

## 12. Milestones (target 8–9 h)

| # | Milestone | Est. |
|---|---|---|
| M0 | Project skeleton: pyproject, package, config from env, CLI stub, test + lint setup, AI-usage log | 0.5 h |
| M1 | Mock EHR: schema, service, idempotency, FaultPlan, out-of-band hooks, audit log + tests | 1.5 h |
| M2 | Tool layer: typed IDs, scoping guards, action_id/idempotency, retry/reconcile, read-back, ToolResult + tests | 1.5 h |
| M3 | Agent: LLM client + adapter, prompt, ConversationState, OutcomeLedger, claim guard, CLI chat, JSONL traces + tests → **tag `v0-baseline`** | 1.75 h |
| M4 | Eval harness: scenario JSON, scripted patient, graders, runner, scoring, baseline, exit codes, failure reports + tests | 1.75 h |
| M5 | Improvement loop on genuine failures: run → report → IMP record → fix → re-run → **tag `v1`** | 1 h |
| M6 | README (two commands), DESIGN, INCIDENT answer, RUBRIC blind spots, AI usage, time spent | 0.75 h |

**Cut line if behind schedule:** reduce scenario suite to the 8 most important (drop S3, C1), skip the
secondary success-language detector refinements, keep docs minimal but complete.

**Commit discipline:** the v0 agent is our honest best version; scenarios are added; the failing run is
recorded; improvements land as separate `IMP-NNN` commits. No squashing; no capability is disabled to
create a failure.

### Easy-to-overlook requirements

- F2 and F3 each contain **two** failures; F3's second failure spans **two calls** (multi-session scenario).
- "Error **after** creating a record" is distinct from a plain failure.
- The commit history is audited.
- Design note must include before/after scores and one change for a real clinic.
- The written answer must use our own traces → `call_id` correlation with the EHR audit log.
- AI usage notes and time tracking start now, not at the end.
