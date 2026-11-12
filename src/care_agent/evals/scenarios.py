"""The evaluation scenarios E1-E6, one per assignment failure pattern (plus E6).

Each scenario is explicit: who calls, what the caller says (a fixed script, no
second LLM), which faults the EHR injects, what changes outside the call, and
which EHR facts must hold at the end. Grading reads the EHR, not the
transcript (see ``grading``).

All scenarios run against the demo seed with a fixed clock (EVAL_NOW, a
Thursday), so slot IDs and dates are the same on every run.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from care_agent.ehr import repository as repo
from care_agent.ehr import service
from care_agent.ehr.faults import FaultMode, FaultPlan

EVAL_NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)  # Thursday 12 November 2026

MARIA_PHONE = "+15550100001"
LUIS_PHONE = "+15550100002"
MARIA_INTRO = "My name is Maria Garcia, date of birth 14 March 1985."
MARIA_CHECKUP = "apt_mariacheckup"  # seeded: Monday 16 November 10:00 with Dr Kim
FRI_0900_LEE = "slot_202611130900lee"
FRI_1000_KIM = "slot_202611131000kim"


@dataclass(frozen=True)
class Expectation:
    """One EHR fact that must hold at the end of the call."""

    name: str
    check: Callable[[sqlite3.Connection, str], bool]  # (conn, call_id) -> holds?
    description: str


@dataclass(frozen=True)
class Scenario:
    id: str
    failure_pattern: str
    title: str
    caller_phone: str
    patient_turns: tuple[str, ...]
    expectations: tuple[Expectation, ...]
    faults: Callable[[], FaultPlan] = FaultPlan
    # Changes made in the EHR by someone else, keyed by the index of the caller
    # turn they happen before (e.g. the clinic cancels between turn 0 and 1).
    external_changes: dict[int, Callable[[sqlite3.Connection], None]] = field(default_factory=dict)


# --- EHR fact helpers -------------------------------------------------------------


def _count(conn: sqlite3.Connection, sql: str, *params: object) -> int:
    return conn.execute(sql, params).fetchone()[0]


def booked_in_slot(conn: sqlite3.Connection, patient_id: str, slot_id: str) -> int:
    return _count(
        conn,
        "SELECT count(*) FROM appointments WHERE patient_id = ? AND slot_id = ? "
        "AND status = 'booked'",
        patient_id,
        slot_id,
    )


def appointments_of(conn: sqlite3.Connection, patient_id: str) -> int:
    return _count(conn, "SELECT count(*) FROM appointments WHERE patient_id = ?", patient_id)


def escalations_for_call(conn: sqlite3.Connection, call_id: str) -> int:
    return _count(conn, "SELECT count(*) FROM escalations WHERE call_id = ?", call_id)


def patient_count(conn: sqlite3.Connection) -> int:
    return _count(conn, "SELECT count(*) FROM patients")


def checkup(conn: sqlite3.Connection):
    appointment = repo.get_appointment(conn, MARIA_CHECKUP)
    assert appointment is not None
    return appointment


def _clinic_cancels_checkup(conn: sqlite3.Connection) -> None:
    current = checkup(conn)
    service.cancel_appointment(
        conn,
        MARIA_CHECKUP,
        expected_version=current.version,
        now=EVAL_NOW,
        reason="cancelled by the patient through the clinic front desk",
    )


# --- Scenarios --------------------------------------------------------------------

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="E1",
        failure_pattern="F1",
        title="Booking times out after the EHR committed it",
        caller_phone=MARIA_PHONE,
        patient_turns=(
            f"Hi. {MARIA_INTRO} I'd like to book a cleaning on Friday 13 November at 09:00 "
            "with Dr Lee.",
            "Yes, please book it.",
            "Great, thank you. That's all.",
        ),
        faults=lambda: FaultPlan({"book_appointment": [FaultMode.TIMEOUT_AFTER_COMMIT]}),
        expectations=(
            Expectation(
                "booking_exists_once",
                lambda conn, call: booked_in_slot(conn, "pat_maria", FRI_0900_LEE) == 1,
                "Maria has exactly one booked appointment in the Friday 09:00 slot",
            ),
            Expectation(
                "no_duplicate_appointments",
                lambda conn, call: appointments_of(conn, "pat_maria") <= 2,
                "Maria has no extra appointments: at most the seeded check-up and one new one",
            ),
        ),
    ),
    Scenario(
        id="E2",
        failure_pattern="F2",
        title="Escalation errors after commit and the caller asks again",
        caller_phone=LUIS_PHONE,
        patient_turns=(
            "Hello, I'm Luis Garcia, born 2 July 1983. I'd like a member of staff to call me "
            "back about my bill.",
            "Can you make sure someone really calls me back?",
            "Okay, thanks. Goodbye.",
        ),
        faults=lambda: FaultPlan({"create_escalation": [FaultMode.ERROR_AFTER_COMMIT]}),
        expectations=(
            Expectation(
                "escalation_exists_once",
                lambda conn, call: escalations_for_call(conn, call) == 1,
                "Exactly one escalation exists for this call",
            ),
        ),
    ),
    Scenario(
        id="E3",
        failure_pattern="F3",
        title="Existing patient calls from her husband's phone",
        caller_phone=LUIS_PHONE,
        patient_turns=(
            f"Hi, I'm calling from my husband's phone. {MARIA_INTRO}",
            "I'd like to book a cleaning on Friday 13 November at 10:00 with Dr Kim.",
            "Yes, please book it.",
            "Thank you, bye.",
        ),
        expectations=(
            Expectation(
                "booked_for_maria",
                lambda conn, call: booked_in_slot(conn, "pat_maria", FRI_1000_KIM) == 1,
                "The Friday 10:00 slot is booked for Maria (pat_maria)",
            ),
            Expectation(
                "nothing_booked_for_luis",
                lambda conn, call: appointments_of(conn, "pat_luis") == 0,
                "Luis, whose phone it is, has no appointments",
            ),
            Expectation(
                "no_duplicate_patient",
                lambda conn, call: patient_count(conn) == 2,
                "No new patient record was created",
            ),
        ),
    ),
    Scenario(
        id="E4",
        failure_pattern="F4",
        title="Cancel 'my check-up' (service name vs appointment ID)",
        caller_phone=MARIA_PHONE,
        patient_turns=(
            f"Hello. {MARIA_INTRO} Please cancel my check-up.",
            "Yes, please cancel it.",
            "Thanks, that's all.",
        ),
        expectations=(
            Expectation(
                "checkup_cancelled",
                lambda conn, call: checkup(conn).status == "cancelled",
                "The seeded check-up appointment is cancelled",
            ),
            Expectation(
                "no_other_changes",
                lambda conn, call: appointments_of(conn, "pat_maria") == 1,
                "Maria has no new appointments",
            ),
        ),
    ),
    Scenario(
        id="E5",
        failure_pattern="F5",
        title="Appointment cancelled at the clinic after the agent read it",
        caller_phone=MARIA_PHONE,
        patient_turns=(
            f"Hi. {MARIA_INTRO} What appointments do I have?",
            "Please move my check-up to Tuesday 17 November at 09:00.",
            "Yes, go ahead.",
            "Okay, thank you.",
        ),
        external_changes={1: _clinic_cancels_checkup},
        expectations=(
            Expectation(
                "cancelled_appointment_not_moved",
                lambda conn, call: (
                    checkup(conn).status == "cancelled"
                    and checkup(conn).slot_id == "slot_202611161000kim"
                    and checkup(conn).version == 2
                ),
                "The externally cancelled check-up was not touched again (still cancelled, "
                "original slot, version 2)",
            ),
        ),
    ),
    Scenario(
        id="E6",
        failure_pattern="F1 (cancel)",
        title="Cancellation never commits; the agent must not claim it did",
        caller_phone=MARIA_PHONE,
        patient_turns=(
            f"Hello. {MARIA_INTRO} Please cancel my check-up.",
            "Yes, cancel it.",
            "So is my check-up cancelled now?",
        ),
        # The EHR rejects every cancellation attempt in this call.
        faults=lambda: FaultPlan({"cancel_appointment": [FaultMode.TIMEOUT_BEFORE_COMMIT] * 30}),
        expectations=(
            Expectation(
                "checkup_unchanged",
                lambda conn, call: checkup(conn).status == "booked" and checkup(conn).version == 1,
                "The check-up is still booked and unchanged",
            ),
        ),
    ),
)

SCENARIOS_BY_ID = {scenario.id: scenario for scenario in SCENARIOS}
