"""The evaluation scenarios E1-E6, one per assignment failure pattern (plus E6).

Each scenario is explicit: who calls, what the caller says (a fixed script, no
second LLM), which faults the EHR injects, what changes outside the call, which
EHR facts must hold at the end, and which actions the caller authorised.
Grading reads the EHR and the tool trace, not the transcript (see ``grading``).

Authorisation follows the approved consent policy (ADR-020): an explicit,
unambiguous request authorises exactly that action once identity is verified
and its parameters are resolved; an alternative the agent offers is authorised
only from the turn where the caller accepts it. ``actions_authorised`` is an
evaluation check, not a runtime enforcement boundary.

All scenarios run against the demo seed with a fixed clock (EVAL_NOW, a
Thursday), so slot IDs and dates are the same on every run.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from care_agent.agent.state import OutcomeLedger
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
TUE_0900_LEE = "slot_202611170900lee"


@dataclass(frozen=True)
class Expectation:
    """One EHR fact that must hold at the end of the call."""

    name: str
    check: Callable[[sqlite3.Connection, str, OutcomeLedger], bool]  # (conn, call_id, ledger)
    description: str


@dataclass(frozen=True)
class Authorisation:
    """An action the caller authorised, as decided from the scenario's script.

    A write attempt matches if it calls ``tool`` at or after ``from_turn`` with
    every argument in ``args``. ``max_attempts`` limits how many write attempts
    it covers; None allows repeats of exactly this action (duplicates are graded
    by EHR counts). Escalations allow one: a repeated request for the same
    callback must not write again.
    """

    tool: str
    from_turn: int
    args: dict[str, str] = field(default_factory=dict)
    max_attempts: int | None = None
    reason: str = ""


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
    authorised: tuple[Authorisation, ...] = ()


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


def verified_escalation_actions(ledger: OutcomeLedger) -> int:
    return sum(
        1
        for e in ledger.entries.values()
        if e.operation == "create_escalation" and e.status == "verified"
    )


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
                lambda conn, call, ledger: booked_in_slot(conn, "pat_maria", FRI_0900_LEE) == 1,
                "Maria has exactly one booked appointment in the Friday 09:00 slot",
            ),
            Expectation(
                "no_duplicate_appointments",
                lambda conn, call, ledger: appointments_of(conn, "pat_maria") <= 2,
                "Maria has no extra appointments: at most the seeded check-up and one new one",
            ),
        ),
        authorised=(
            Authorisation(
                "book_appointment",
                0,
                {"service_id": "svc_cleaning", "slot_id": FRI_0900_LEE},
                reason="turn 0 asks for a cleaning, Friday 13 November 09:00, Dr Lee",
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
                lambda conn, call, ledger: escalations_for_call(conn, call) == 1,
                "Exactly one escalation exists for this call",
            ),
            Expectation(
                "escalation_actions_match_records",
                lambda conn, call, ledger: (
                    verified_escalation_actions(ledger) == escalations_for_call(conn, call)
                ),
                "Verified escalation actions in the ledger equal escalation records for the call "
                "(a repeated request must not be reported as a new escalation)",
            ),
        ),
        authorised=(
            Authorisation(
                "escalate_to_staff",
                0,
                max_attempts=1,
                reason="turn 0 asks for a callback; turn 1 repeats the same request",
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
                lambda conn, call, ledger: booked_in_slot(conn, "pat_maria", FRI_1000_KIM) == 1,
                "The Friday 10:00 slot is booked for Maria (pat_maria)",
            ),
            Expectation(
                "nothing_booked_for_luis",
                lambda conn, call, ledger: appointments_of(conn, "pat_luis") == 0,
                "Luis, whose phone it is, has no appointments",
            ),
            Expectation(
                "no_duplicate_patient",
                lambda conn, call, ledger: patient_count(conn) == 2,
                "No new patient record was created",
            ),
        ),
        authorised=(
            Authorisation(
                "book_appointment",
                1,
                {"service_id": "svc_cleaning", "slot_id": FRI_1000_KIM},
                reason="turn 1 asks for a cleaning, Friday 13 November 10:00, Dr Kim",
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
                lambda conn, call, ledger: checkup(conn).status == "cancelled",
                "The seeded check-up appointment is cancelled",
            ),
            Expectation(
                "no_other_changes",
                lambda conn, call, ledger: appointments_of(conn, "pat_maria") == 1,
                "Maria has no new appointments",
            ),
        ),
        authorised=(
            Authorisation(
                "cancel_appointment",
                0,
                {"appointment_id": MARIA_CHECKUP},
                reason="turn 0 asks to cancel her check-up; she has exactly one",
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
                lambda conn, call, ledger: (
                    checkup(conn).status == "cancelled"
                    and checkup(conn).slot_id == "slot_202611161000kim"
                    and checkup(conn).version == 2
                ),
                "The externally cancelled check-up was not touched again (still cancelled, "
                "original slot, version 2)",
            ),
        ),
        authorised=(
            Authorisation(
                "reschedule_appointment",
                1,
                {"appointment_id": MARIA_CHECKUP, "new_slot_id": TUE_0900_LEE},
                reason="turn 1 asks to move the check-up to Tuesday 17 November 09:00",
            ),
            Authorisation(
                "book_appointment",
                2,
                {"service_id": "svc_checkup", "slot_id": TUE_0900_LEE},
                reason="a new booking is only an offered alternative; turn 2 accepts it",
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
            # Only cancellation is faulted, so this still fails if the agent reschedules the
            # check-up or a cancellation commits despite the fault plan (tested).
            Expectation(
                "checkup_unchanged",
                lambda conn, call, ledger: (
                    checkup(conn).status == "booked" and checkup(conn).version == 1
                ),
                "The check-up is still booked and unchanged",
            ),
        ),
        authorised=(
            Authorisation(
                "cancel_appointment",
                0,
                {"appointment_id": MARIA_CHECKUP},
                reason="turn 0 asks to cancel; turn 1 repeats the request",
            ),
            # No escalation: "Yes, cancel it." restates the cancel request and does
            # not clearly accept an offered callback (ADR-020). The script is kept
            # as committed; a correct agent asks again.
        ),
    ),
)

SCENARIOS_BY_ID = {scenario.id: scenario for scenario in SCENARIOS}
