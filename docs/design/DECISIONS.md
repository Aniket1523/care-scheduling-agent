# Architectural Decisions

Lightweight decision records. Each entry: context → decision → consequences. Status is one of
**Accepted**, **Pending**, **Superseded**. Changes to an Accepted decision require product-owner approval
and a new entry that supersedes the old one.

---

## ADR-001 — Language and tooling
**Status:** Accepted (2026-11-12)
**Decision:** `requires-python = ">=3.12"`; development on Python 3.14.10 in the existing `.venv`.
Dependencies declared in `pyproject.toml`, installed with `pip install -e ".[dev]"`. Tooling: pytest, Ruff
(lint + format, `target-version = "py312"`). No uv, no mypy. Developer shell is Windows CMD; documented
commands use CMD syntax.
**Why:** Matches the existing environment; fewest moving parts; 3.12 floor keeps the code portable for
reviewers.
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
`LLM_TEMPERATURE`, read directly from the environment. No `.env` loader for now (`python-dotenv` may be
added later if needed); `.env.example` documents the names only. The key is never logged and is masked
in `repr`.
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
**Status:** Accepted (modified per second review, 2026-11-12)
**Decision:** A unique `action_id` is minted for each **logical operation**; the EHR idempotency key is
derived from it and **reused across retries** (internal tool-layer retries, and model-level retries that
pass back the `action_id` from a previous `ToolResult`). A **new user intention** — a write call without
an `action_id` — gets a new one. The request **fingerprint** (hash of normalised arguments) is stored with
the key and used **only** to reject reuse of an existing key with different arguments
(`IDEMPOTENCY_KEY_REUSED`). It is never used to classify retry vs. new intention.
**Rejected:** Fingerprint-based retry detection — it guesses intent from arguments, and wrongly merges a
genuine repeat request with an earlier one (or splits a retry whose arguments were re-phrased).
**Why:** F2 (retry created a second escalation) and the error-after-commit requirement.
**Consequences:** If the model starts a *new* action for what is really the same intention, idempotency
does not catch it; EHR domain constraints (one booking per slot, one open escalation per call) are the
backstop, and eval trace checks surface it. Cross-call duplicates (F3) are handled by identity resolution
and the EHR duplicate check.

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

## ADR-019 — Identity is verified by name + DOB; phone is only a hint
**Status:** Accepted (2026-11-12, owner decision during M1b review)
**Decision:** A patient's identity is verified by first name, last name and date of birth. The
caller's phone number is a lookup hint only: among name + DOB matches, a record holding that phone is
preferred, which can separate duplicate records. A phone-only match never verifies identity; if any of
the three details is missing, `resolve_identity` returns `verification_required` without revealing
anything about the phone's holders. If the phone belongs to another patient (F3, spouse's phone), the
name + DOB match decides. Ambiguous matches stay ambiguous. Lookup never creates a patient.
**Supersedes:** "Identify the caller by caller-ID phone; fall back to name + DOB" in `ANALYSIS.md`
(§4, §10) and the phone-only `lookup_caller` tool in §7.2, which is revisited in M2.
**Why:** Caller ID can belong to someone else (F3) and can be spoofed; acting on the wrong patient's
record is worse than asking two questions.
