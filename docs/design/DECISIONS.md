# Architectural Decisions

Lightweight decision records. Each entry: context → decision → consequences. Status is one of
**Accepted**, **Pending**, **Superseded**. Changes to an Accepted decision require product-owner approval
and a new entry that supersedes the old one.

---

## ADR-001 — Language and tooling
**Status:** Accepted (2026-11-12)
**Decision:** Python 3.14 (existing `.venv`, 3.14.10). Dependencies declared in `pyproject.toml`, installed
with `pip install -e ".[dev]"`. Tooling: pytest, Ruff (lint + format). No uv, no mypy.
**Why:** Matches the existing environment; fewest moving parts.
**Consequences:** Type safety comes from Pydantic validation at boundaries and type hints (unchecked
statically). Revisit mypy only with a specific reason.

## ADR-002 — In-process mock EHR, no HTTP layer
**Status:** Accepted
**Decision:** The EHR is an in-process service behind an `EHRClient` protocol. No FastAPI initially.
**Why:** Same semantics as an HTTP backend for everything graded — including "the write committed but the
client saw a timeout" — while being deterministic and fast. An HTTP layer adds a server process, ports and
wall-clock flakiness to every eval.
**Rejected:** FastAPI service (possible stretch wrapper later, behind the same protocol).
**Consequences:** Timeouts are simulated by the fault injector, not by real sockets.

## ADR-003 — SQLite via stdlib `sqlite3`, no ORM
**Status:** Accepted
**Decision:** Explicit SQL; partial unique indexes enforce invariants (one booking per slot, one open
escalation per call); write + idempotency record in one transaction; fresh DB file in a system temp
directory per run/test.
**Why:** Zero extra dependencies; database-level guarantees; every line explainable. Temp dir avoids
OneDrive file locking.

## ADR-004 — Custom LLM tool-calling loop
**Status:** Accepted
**Decision:** Own agent loop behind an `LLMClient` protocol; no agent framework. A `ScriptedLLM`
implementation drives unit tests without network access.
**Why:** Small, explainable, fully testable.

## ADR-005 — Externalised LLM configuration
**Status:** Accepted
**Decision:** `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS`,
`LLM_TEMPERATURE` from the environment (optional git-ignored `.env`; `.env.example` lists names only).
The key is never logged and is masked in `repr`.
**Why:** No secrets in the repo; provider/model swappable; Claude Code access is **not** assumed to provide
API access.
**Consequences:** Unit tests require no key; `chat` and `eval` fail fast with a clear message if
configuration is missing.

## ADR-006 — First LLM provider adapter
**Status:** Pending (decide before M3)
**Question:** Which provider SDK/adapter to implement first (depends on which API key the owner has).
**Constraint:** Adapter is isolated behind `LLMClient`; adding a second provider must not touch agent code.

## ADR-007 — Typed ID prefixes + Pydantic validation
**Status:** Accepted
**Decision:** IDs carry prefixes (`pat_`, `prv_`, `svc_`, `slot_`, `apt_`, `esc_`, `act_`); tool arguments
are Pydantic models that reject the wrong prefix.
**Why:** Makes F4 (service ID in place of appointment ID) a structured validation error at the tool
boundary, returned to the model, instead of a backend failure.

## ADR-008 — Patient ID from the verified session
**Status:** Accepted
**Decision:** Tools that act for a patient use the session's verified `patient_id`; the LLM never passes
it. Ownership of an appointment is checked before cancel/reschedule.
**Why:** Removes a class of wrong-ID and cross-patient errors.

## ADR-009 — Action identity and idempotency
**Status:** Accepted (modified per review)
**Decision:** The tool layer mints an `action_id` per **logical operation**; the EHR idempotency key is
derived from it and **reused across retries**. A write fingerprint (call_id, operation, normalised target
args) decides whether an LLM invocation continues an existing action (`pending`/`unknown` → reuse;
`verified_success` → return existing outcome) or is a genuinely new intention (no match, or previous
attempt definitively `failed` → new `action_id`). The LLM never supplies idempotency keys.
**Why:** F2 (retry created a second escalation) and the error-after-commit requirement.
**Consequences:** Cross-call duplicates (F3) are handled by identity resolution and the EHR duplicate
check, not by idempotency.

## ADR-010 — Read-after-write verification + OutcomeLedger
**Status:** Accepted
**Decision:** After every write (and after reconciliation of an unknown outcome) the tool layer reads the
record back; `verified=true` only if backend state matches. Outcomes are recorded in a per-call
`OutcomeLedger` (`pending | verified_success | failed | unknown`).
**Why:** Defines "it happened" as "the backend shows it", per R5.

## ADR-011 — Structured claim guard
**Status:** Accepted (modified per review)
**Decision:** The agent replies via `reply_to_patient(message, confirmed_action_ids)`. Each confirmed
action must be `verified_success` in the ledger; confirmation details are rendered from verified backend
data. A success-language detector is a secondary backstop only. Blocked replies get one corrective
re-prompt, then a deterministic ledger-based fallback.
**Why:** Keyword matching alone is brittle; structured outcomes are checkable.

## ADR-012 — Atomic reschedule
**Status:** Accepted
**Decision:** Reschedule is one EHR operation (move slot, bump version) in one transaction.
**Why:** Cancel-then-book can fail halfway and leave the patient with nothing.

## ADR-013 — Live reads before mutation; optimistic concurrency
**Status:** Accepted
**Decision:** The tool layer re-reads an appointment before cancel/reschedule and passes
`expected_version`; the EHR rejects stale versions with `STALE_VERSION`.
**Why:** F5.

## ADR-014 — Evaluation design
**Status:** Accepted (modified per review)
**Decision:** 8–10 scenarios; genuine LLM agent vs **scripted deterministic patient simulator**; grading
by backend-state, trace and structured-claim checks; **no LLM judge** and **single trial** initially;
gating checks for unverified claims and duplicate records; scenarios in JSON validated by Pydantic.
**Why:** Deterministic, cheap, explainable grading focused on the failure modes that matter.
**Consequences:** Narrow patient behaviour and single-trial variance are documented blind spots.

## ADR-015 — Regression gate
**Status:** Accepted
**Decision:** `evals/baseline.json` records per-scenario pass/fail; `eval` exits non-zero if any
baseline-passing scenario fails; baseline changes only via `--update-baseline`.

## ADR-016 — Improvement loop
**Status:** Accepted (modified per review)
**Decision:** Structured failure reports are generated automatically per run. Improvement records
(`improvements/IMP-NNN.md`) are written and reviewed by a human. **No automatic code modification.**

## ADR-017 — Observability
**Status:** Accepted
**Decision:** JSONL trace per call keyed by `call_id`; EHR `audit_log` rows carry `call_id` and
`action_id`.
**Why:** Supports failure reports and the written incident investigation.

## ADR-018 — Commit discipline
**Status:** Accepted
**Decision:** Honest v0 tagged `v0-baseline`; scenarios, failing run and each `IMP-NNN` fix as separate
commits; final tagged `v1`. No squashing. No capability disabled to manufacture a failure.
