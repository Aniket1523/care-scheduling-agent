"""Run one scenario: fresh seeded EHR, scripted caller, real agent code, graded.

The trace is built from the agent's own conversation history, so it records
exactly the tool calls the model made and the results it was sent back. After
each turn it also takes the tool layer's internal attempt log (retries, injected
faults, reconciliation reads), which the model never sees.
"""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google.genai import types

from care_agent.agent.loop import Agent, ModelClient
from care_agent.agent.state import ConversationState
from care_agent.agent.tools import ToolRunner
from care_agent.ehr.db import connect, init_db
from care_agent.ehr.seed import seed_demo_data
from care_agent.evals.grading import (
    WRITE_TOOLS,
    Check,
    grade,
    snapshot_appointments,
    write_attempts,
)
from care_agent.evals.scenarios import EVAL_NOW, Scenario


@dataclass
class ScenarioResult:
    scenario_id: str
    status: str  # "pass" | "fail" | "error"
    checks: list[Check]
    events: list[dict[str, Any]]
    model_calls: int
    error: str | None = None
    replies: list[str] = field(default_factory=list)

    @property
    def failed_checks(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    @property
    def guard_rejections(self) -> int:
        """Replies the claim guard rejected (reported, not graded)."""
        return sum(
            1
            for e in self.events
            if e["event"] == "tool_result"
            and e["tool"] == "reply_to_patient"
            and e["result"].get("status") == "rejected"
        )


class _CountingClient:
    def __init__(self, inner: ModelClient) -> None:
        self.inner = inner
        self.calls = 0

    def generate(self, contents: list[types.Content]) -> types.Content:
        self.calls += 1
        return self.inner.generate(contents)


def run_scenario(scenario: Scenario, client: ModelClient) -> ScenarioResult:
    counting = _CountingClient(client)
    with tempfile.TemporaryDirectory(prefix=f"care_eval_{scenario.id}_") as tmp:
        conn = connect(Path(tmp) / "ehr.sqlite3")
        try:
            return _run(scenario, conn, counting)
        finally:
            conn.close()


def _run(scenario: Scenario, conn: sqlite3.Connection, client: _CountingClient) -> ScenarioResult:
    init_db(conn)
    seed_demo_data(conn, EVAL_NOW)
    before = snapshot_appointments(conn)
    state = ConversationState(
        call_id=f"call_{scenario.id.lower()}", caller_phone=scenario.caller_phone
    )
    tools = ToolRunner(conn, state, lambda: EVAL_NOW, scenario.faults())
    agent = Agent(client, tools, state)

    events: list[dict[str, Any]] = []
    replies: list[str] = []
    error = None
    for turn, text in enumerate(scenario.patient_turns):
        if turn in scenario.external_changes:
            scenario.external_changes[turn](conn)
            events.append({"turn": turn, "event": "external_change"})
        events.append({"turn": turn, "event": "caller", "text": text})
        start = len(agent.history)
        agent.last_model_error = None
        reply = agent.respond(text)
        events.extend(_history_events(turn, agent.history[start:]))
        events.extend({"turn": turn, **entry} for entry in tools.attempt_log)
        tools.attempt_log.clear()
        events.append({"turn": turn, "event": "agent_reply", "text": reply})
        replies.append(reply)
        if agent.last_model_error is not None:
            exc = agent.last_model_error
            error = f"{type(exc).__name__}: {exc}"[:500]
            events.append({"turn": turn, "event": "model_error", "error": error})
            break

    events.append({"event": "ehr_state", **_ehr_state(conn, state.call_id)})
    events.append(
        {
            "event": "ledger",
            "entries": [
                {"action_id": e.action_id, "operation": e.operation, "status": e.status}
                for e in state.ledger.entries.values()
            ],
        }
    )
    checks = grade(scenario, conn, state.call_id, before, replies, state.ledger, events)
    status = "pass" if all(c.passed for c in checks) else "fail"
    if error is not None:
        status = "error"  # the call did not finish, so its grade proves nothing
    return ScenarioResult(scenario.id, status, checks, events, client.calls, error, replies)


def _history_events(turn: int, contents: list[types.Content]) -> list[dict[str, Any]]:
    events = []
    for content in contents:
        for part in content.parts or []:
            if part.function_call is not None:
                events.append(
                    {
                        "turn": turn,
                        "event": "tool_call",
                        "tool": part.function_call.name,
                        "args": dict(part.function_call.args or {}),
                    }
                )
            elif part.function_response is not None:
                events.append(
                    {
                        "turn": turn,
                        "event": "tool_result",
                        "tool": part.function_response.name,
                        "result": part.function_response.response,
                    }
                )
    return events


def _ehr_state(conn: sqlite3.Connection, call_id: str) -> dict[str, Any]:
    appointments = conn.execute(
        "SELECT id, patient_id, slot_id, status, version FROM appointments ORDER BY id"
    ).fetchall()
    escalations = conn.execute(
        "SELECT id, call_id, status FROM escalations WHERE call_id = ?", (call_id,)
    ).fetchall()
    return {
        "appointments": [dict(row) for row in appointments],
        "escalations": [dict(row) for row in escalations],
        "patients": conn.execute("SELECT count(*) FROM patients").fetchone()[0],
    }


# --- Failure reports ---------------------------------------------------------------

# Where a failed check most likely points, before anyone has read the trace.
_CHECK_HINTS = {
    "claims_match_ehr": (
        "unverified_claim",
        "claim guard / prompt",
        "The agent told the caller something the EHR does not show.",
    ),
    "booking_exists_once": (
        "missing_or_duplicate_write",
        "tool retry + reconciliation / prompt",
        "The booking is missing or duplicated.",
    ),
    "no_duplicate_appointments": (
        "duplicate_record",
        "tool retry / idempotency",
        "More appointments exist than expected.",
    ),
    "escalation_exists_once": (
        "missing_or_duplicate_write",
        "tool retry / idempotency / prompt",
        "The escalation is missing or duplicated.",
    ),
    "booked_for_maria": (
        "identity_miss",
        "identity verification / prompt",
        "Maria was not booked.",
    ),
    "nothing_booked_for_luis": (
        "wrong_patient",
        "identity verification",
        "The phone owner was booked instead of the caller.",
    ),
    "no_duplicate_patient": (
        "duplicate_record",
        "identity verification / registration guard",
        "A duplicate patient record was created.",
    ),
    "checkup_cancelled": ("task_incomplete", "prompt / tool", "The check-up was not cancelled."),
    "no_other_changes": ("unexpected_write", "prompt / tool", "Unexpected appointments exist."),
    "cancelled_appointment_not_moved": (
        "stale_state",
        "version checks / tool reconciliation",
        "An appointment cancelled elsewhere was changed again.",
    ),
    "actions_authorised": (
        "unauthorised_action",
        "prompt (consent policy, ADR-020)",
        "The agent attempted a write the caller had not authorised.",
    ),
    "escalation_actions_match_records": (
        "misreported_write",
        "escalation tool result / ledger",
        "More escalations were reported as verified than exist in the EHR.",
    ),
    "checkup_unchanged": (
        "state_changed_on_failure",
        "tool reconciliation / EHR transaction",
        "A cancellation that never committed changed the record.",
    ),
}


def failure_report(scenario: Scenario, result: ScenarioResult) -> dict[str, Any]:
    tool_calls = [e for e in result.events if e["event"] == "tool_call"]
    tool_errors = [
        {"tool": e["tool"], "code": (e["result"].get("error") or {}).get("code")}
        for e in result.events
        if e["event"] == "tool_result" and e["result"].get("status") == "failed"
    ]
    attempted_writes = sorted({e["tool"] for e in tool_calls if e["tool"] in WRITE_TOOLS})
    findings = []
    for check in result.failed_checks:
        category, layer, observed = _CHECK_HINTS.get(
            check.name, ("unknown", "needs review", check.description)
        )
        findings.append(
            {
                "check": check.name,
                "expected": check.description,
                "observed": observed + (f" ({check.detail})" if check.detail else ""),
                "category": category,
                "suggested_fix_layer": layer,
            }
        )
    if result.status == "error":
        likely = f"The model call failed: {result.error}. Not an agent behaviour failure."
    elif not attempted_writes and any(
        f["category"] in {"task_incomplete", "missing_or_duplicate_write", "identity_miss"}
        for f in findings
    ):
        likely = (
            "The model never called a write tool. Check whether it asked a question the "
            "scripted caller does not answer, or misread a tool result."
        )
    elif tool_errors:
        likely = "Tool calls failed: " + ", ".join(f"{e['tool']}={e['code']}" for e in tool_errors)
    else:
        likely = "See findings; read the trace for this scenario."
    return {
        "scenario_id": scenario.id,
        "failure_pattern": scenario.failure_pattern,
        "title": scenario.title,
        "status": result.status,
        "findings": findings,
        "likely_root_cause": likely,
        "attempted_writes": attempted_writes,
        "write_attempts": [
            {"turn": a.turn, "tool": a.tool, "action_id": a.action_id}
            for a in write_attempts(result.events)
        ],
        "guard_rejections": result.guard_rejections,
        "tool_errors": tool_errors,
        "trace": [e for e in result.events if e["event"] != "ehr_state"],
        "final_ehr_state": next(e for e in result.events if e["event"] == "ehr_state"),
    }
