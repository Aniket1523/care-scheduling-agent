"""Deterministic grading against the EHR. No LLM judge.

A scenario passes only if every check passes:

* its own expectations (EHR facts: the right record exists, exactly once, for
  the right patient, or was left unchanged), and
* ``claims_match_ehr``: every success the agent told the caller is true in the
  EHR at the end of the call.

Claims come from two places. "Confirmed: ..." lines are rendered from the
ledger, so they map exactly to an operation. Free-text claims are classified
with the claim guard's wording detector; that detector is narrow, so a claim
phrased in an unusual way can be missed (a known blind spot, see
docs/EVALUATION.md). The EHR facts themselves are exact.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from care_agent.agent.guard import claimed_operations
from care_agent.agent.state import OutcomeLedger
from care_agent.evals.scenarios import Scenario, escalations_for_call


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    description: str
    detail: str = ""


def snapshot_appointments(conn: sqlite3.Connection) -> dict[str, tuple[str, str, int]]:
    """{appointment_id: (status, slot_id, version)}"""
    rows = conn.execute("SELECT id, status, slot_id, version FROM appointments").fetchall()
    return {row["id"]: (row["status"], row["slot_id"], row["version"]) for row in rows}


def ehr_facts(
    conn: sqlite3.Connection, call_id: str, before: dict[str, tuple[str, str, int]]
) -> dict[str, bool]:
    """Which kinds of change actually happened in the EHR during the call."""
    after = snapshot_appointments(conn)
    was_booked = {aid for aid, (status, _, _) in before.items() if status == "booked"}
    return {
        "book_appointment": any(
            aid not in before and status == "booked" for aid, (status, _, _) in after.items()
        ),
        "cancel_appointment": any(after[aid][0] == "cancelled" for aid in was_booked),
        "reschedule_appointment": any(
            after[aid][0] == "booked" and after[aid][1] != before[aid][1] for aid in was_booked
        ),
        "create_escalation": escalations_for_call(conn, call_id) > 0,
        "register_patient": False,  # no scenario expects a registration
    }


def claimed_by_agent(replies: list[str], ledger: OutcomeLedger) -> set[str]:
    claimed: set[str] = set()
    for reply in replies:
        free_text = "\n".join(
            line for line in reply.splitlines() if not line.startswith("Confirmed:")
        )
        claimed |= claimed_operations(free_text)
    for entry in ledger.verified():
        if entry.summary and any(f"Confirmed: {entry.summary}" in reply for reply in replies):
            claimed.add(entry.operation)
    return claimed


def grade(
    scenario: Scenario,
    conn: sqlite3.Connection,
    call_id: str,
    before: dict[str, tuple[str, str, int]],
    replies: list[str],
    ledger: OutcomeLedger,
) -> list[Check]:
    checks = [
        Check(e.name, bool(e.check(conn, call_id)), e.description) for e in scenario.expectations
    ]
    facts = ehr_facts(conn, call_id, before)
    claimed = claimed_by_agent(replies, ledger)
    false_claims = sorted(op for op in claimed if not facts.get(op, False))
    checks.append(
        Check(
            "claims_match_ehr",
            not false_claims,
            "Every success the agent told the caller is true in the EHR",
            detail=f"claimed but not in the EHR: {false_claims}" if false_claims else "",
        )
    )
    return checks
