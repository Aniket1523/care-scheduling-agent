"""M1c: idempotency, escalation, fault injection and version checks."""

from __future__ import annotations

import sqlite3

import pytest

from care_agent.ehr import repository as repo
from care_agent.ehr import service
from care_agent.ehr.db import connect, init_db
from care_agent.ehr.faults import FaultMode, FaultPlan
from care_agent.ehr.service import EHRError, EHRTimeout, ErrorCode
from care_agent.ids import new_id
from ehr_data import NOW, SERVICE_ID, SLOT_1, SLOT_2, SLOT_3, make_patient

CALL_ID = "call-001"


def add_patient(conn, **overrides):
    patient = make_patient(**overrides)
    with conn:
        repo.insert_patient(conn, patient)
    return patient


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def book(conn, patient_id, action_id, slot=SLOT_1, faults=None):
    return service.book_appointment(
        conn, patient_id, SERVICE_ID, slot[0], action_id=action_id, now=NOW, faults=faults
    )


def escalate(conn, action_id, reason="patient asked for a human", call_id=CALL_ID, faults=None):
    return service.create_escalation(
        conn, call_id, reason, action_id=action_id, now=NOW, faults=faults
    )


# --- Idempotent booking ----------------------------------------------------------


def test_repeating_a_booking_action_returns_the_original_appointment(conn):
    maria = add_patient(conn)
    action_id = new_id("act")
    first = book(conn, maria.id, action_id)
    second = book(conn, maria.id, action_id)
    assert second == first
    assert count(conn, "appointments") == 1


def test_reusing_an_action_id_with_different_arguments_is_a_conflict(conn):
    maria = add_patient(conn)
    action_id = new_id("act")
    book(conn, maria.id, action_id, slot=SLOT_1)
    with pytest.raises(EHRError) as exc_info:
        book(conn, maria.id, action_id, slot=SLOT_2)
    assert exc_info.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
    assert count(conn, "appointments") == 1


def test_reusing_an_action_id_for_another_operation_is_a_conflict(conn):
    maria = add_patient(conn)
    action_id = new_id("act")
    book(conn, maria.id, action_id)
    with pytest.raises(EHRError) as exc_info:
        escalate(conn, action_id)
    assert exc_info.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
    assert count(conn, "escalations") == 0


def test_a_new_action_id_is_a_new_booking_attempt(conn):
    # Same arguments, new action: a genuinely new request, so the slot is taken.
    maria = add_patient(conn)
    book(conn, maria.id, new_id("act"))
    with pytest.raises(EHRError) as exc_info:
        book(conn, maria.id, new_id("act"))
    assert exc_info.value.code == ErrorCode.SLOT_UNAVAILABLE
    assert count(conn, "appointments") == 1


def test_action_id_must_have_the_act_prefix(conn):
    maria = add_patient(conn)
    with pytest.raises(EHRError) as exc_info:
        book(conn, maria.id, "apt_123")
    assert exc_info.value.code == ErrorCode.INVALID_ID


# --- Fault injection on booking --------------------------------------------------


def test_timeout_before_commit_leaves_no_record_and_retry_books_once(conn):
    maria = add_patient(conn)
    action_id = new_id("act")
    faults = FaultPlan({"book_appointment": [FaultMode.TIMEOUT_BEFORE_COMMIT]})
    with pytest.raises(EHRTimeout):
        book(conn, maria.id, action_id, faults=faults)
    assert count(conn, "appointments") == 0
    assert count(conn, "idempotency_keys") == 0  # rolled back together

    retried = book(conn, maria.id, action_id, faults=faults)
    assert retried.status == "booked"
    assert count(conn, "appointments") == 1


@pytest.mark.parametrize(
    ("fault", "raised"),
    [
        (FaultMode.TIMEOUT_AFTER_COMMIT, EHRTimeout),
        (FaultMode.ERROR_AFTER_COMMIT, EHRError),
    ],
)
def test_retry_after_post_commit_failure_does_not_duplicate(conn, fault, raised):
    maria = add_patient(conn)
    action_id = new_id("act")
    faults = FaultPlan({"book_appointment": [fault]})
    with pytest.raises(raised):
        book(conn, maria.id, action_id, faults=faults)
    # The caller saw a failure, but the booking did happen.
    assert count(conn, "appointments") == 1
    created = repo.list_appointments_for_patient(conn, maria.id)[0]

    retried = book(conn, maria.id, action_id, faults=faults)
    assert retried == created
    assert count(conn, "appointments") == 1


def test_fault_queue_is_consumed_in_order(conn):
    maria = add_patient(conn)
    faults = FaultPlan({"book_appointment": [None, FaultMode.ERROR_AFTER_COMMIT]})
    book(conn, maria.id, new_id("act"), slot=SLOT_1, faults=faults)  # no fault
    with pytest.raises(EHRError) as exc_info:
        book(conn, maria.id, new_id("act"), slot=SLOT_2, faults=faults)
    assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
    book(conn, maria.id, new_id("act"), slot=SLOT_3, faults=faults)  # queue empty
    assert count(conn, "appointments") == 3


def test_fault_plan_rejects_unknown_operations():
    with pytest.raises(ValueError):
        FaultPlan({"book_appointmnet": [FaultMode.TIMEOUT_AFTER_COMMIT]})


def test_cancel_timeout_before_commit_leaves_appointment_booked(conn):
    # The written-question case: the patient must not be told it was cancelled.
    maria = add_patient(conn)
    booked = book(conn, maria.id, new_id("act"))
    faults = FaultPlan({"cancel_appointment": [FaultMode.TIMEOUT_BEFORE_COMMIT]})
    with pytest.raises(EHRTimeout):
        service.cancel_appointment(
            conn, booked.id, expected_version=booked.version, now=NOW, faults=faults
        )
    assert repo.get_appointment(conn, booked.id) == booked


def test_cancel_timeout_after_commit_did_cancel(conn):
    maria = add_patient(conn)
    booked = book(conn, maria.id, new_id("act"))
    faults = FaultPlan({"cancel_appointment": [FaultMode.TIMEOUT_AFTER_COMMIT]})
    with pytest.raises(EHRTimeout):
        service.cancel_appointment(
            conn, booked.id, expected_version=booked.version, now=NOW, faults=faults
        )
    assert repo.get_appointment(conn, booked.id).status == "cancelled"


# --- Escalation ------------------------------------------------------------------


def test_create_escalation(conn):
    maria = add_patient(conn)
    outcome = service.create_escalation(
        conn, CALL_ID, "wants a callback", action_id=new_id("act"), now=NOW, patient_id=maria.id
    )
    assert outcome.created
    escalation = outcome.escalation
    assert escalation.id.startswith("esc_")
    assert escalation.status == "open"
    assert escalation.patient_id == maria.id
    assert repo.get_escalation(conn, escalation.id) == escalation


def test_repeating_an_escalation_action_returns_the_original(conn):
    action_id = new_id("act")
    first = escalate(conn, action_id)
    assert escalate(conn, action_id) == first
    assert count(conn, "escalations") == 1


def test_escalation_retry_after_post_commit_error_does_not_duplicate(conn):
    # F2: a retry must not create a second escalation.
    action_id = new_id("act")
    faults = FaultPlan({"create_escalation": [FaultMode.ERROR_AFTER_COMMIT]})
    with pytest.raises(EHRError):
        escalate(conn, action_id, faults=faults)
    assert count(conn, "escalations") == 1
    escalate(conn, action_id, faults=faults)
    assert count(conn, "escalations") == 1


def test_new_escalation_action_for_same_call_returns_the_open_escalation(conn):
    first = escalate(conn, new_id("act"))
    keys_before = count(conn, "idempotency_keys")
    second = escalate(conn, new_id("act"), reason="asked again")
    assert second.escalation == first.escalation
    assert first.created and not second.created
    assert count(conn, "escalations") == 1
    assert count(conn, "idempotency_keys") == keys_before  # a repeat request writes nothing


def test_different_calls_get_separate_escalations(conn):
    escalate(conn, new_id("act"), call_id="call-001")
    escalate(conn, new_id("act"), call_id="call-002")
    assert count(conn, "escalations") == 2


def test_escalation_action_id_reused_with_different_reason_is_a_conflict(conn):
    action_id = new_id("act")
    escalate(conn, action_id, reason="first reason")
    with pytest.raises(EHRError) as exc_info:
        escalate(conn, action_id, reason="other reason")
    assert exc_info.value.code == ErrorCode.IDEMPOTENCY_CONFLICT


def test_escalation_requires_a_reason(conn):
    with pytest.raises(EHRError) as exc_info:
        escalate(conn, new_id("act"), reason="  ")
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT
    assert count(conn, "escalations") == 0


# --- Version checks (F5) ---------------------------------------------------------


def test_stale_cancel_after_external_update_is_rejected(conn):
    # The agent reads the appointment, then staff reschedule it in the EHR.
    maria = add_patient(conn)
    agent_view = book(conn, maria.id, new_id("act"))
    external = service.reschedule_appointment(
        conn, agent_view.id, SLOT_3[0], expected_version=agent_view.version, now=NOW
    )
    with pytest.raises(EHRError) as exc_info:
        service.cancel_appointment(
            conn, agent_view.id, expected_version=agent_view.version, now=NOW
        )
    assert exc_info.value.code == ErrorCode.STALE_VERSION
    assert repo.get_appointment(conn, agent_view.id) == external


def test_stale_reschedule_after_external_cancel_is_rejected(conn):
    # F5: the patient cancelled directly with the clinic after the agent's read.
    maria = add_patient(conn)
    agent_view = book(conn, maria.id, new_id("act"))
    external = service.cancel_appointment(
        conn, agent_view.id, expected_version=agent_view.version, now=NOW
    )
    with pytest.raises(EHRError) as exc_info:
        service.reschedule_appointment(
            conn, agent_view.id, SLOT_3[0], expected_version=agent_view.version, now=NOW
        )
    assert exc_info.value.code == ErrorCode.STALE_VERSION
    assert repo.get_appointment(conn, agent_view.id) == external


def test_version_check_is_part_of_the_update(conn):
    # Even if a stale caller got past the service's read, the UPDATE itself
    # matches no row and changes nothing.
    maria = add_patient(conn)
    booked = book(conn, maria.id, new_id("act"))
    moved = service.reschedule_appointment(
        conn, booked.id, SLOT_3[0], expected_version=booked.version, now=NOW
    )
    with conn:
        assert not repo.mark_cancelled(conn, booked.id, booked.version, None, NOW)
    assert repo.get_appointment(conn, booked.id) == moved


# --- IMP-004: escalation outcomes, replay order and the unique-index race ------------------


def test_escalation_retry_after_error_after_commit_replays_original_creation(conn):
    # The retry must replay "created", not see its own escalation as "already requested".
    action_id = new_id("act")
    faults = FaultPlan({"create_escalation": [FaultMode.ERROR_AFTER_COMMIT]})
    with pytest.raises(EHRError):
        escalate(conn, action_id, faults=faults)
    retried = escalate(conn, action_id, faults=faults)
    assert retried.created
    assert count(conn, "escalations") == 1
    assert count(conn, "idempotency_keys") == 1


def test_concurrent_escalation_insert_resolves_to_already_requested(tmp_path, monkeypatch):
    # Two connections to one database. B's open-escalation read is forced to miss A's commit
    # (the race window), so only the unique index can stop a second open escalation.
    path = tmp_path / "race.sqlite3"
    a, b = connect(path), connect(path)
    try:
        init_db(a)
        first = escalate(a, new_id("act"))
        real_find = repo.find_open_escalation
        reads = []

        def find_open(c, call_id):  # the first read misses A's commit; later reads are real
            reads.append(call_id)
            return None if len(reads) == 1 else real_find(c, call_id)

        monkeypatch.setattr(repo, "find_open_escalation", find_open)
        second = escalate(b, new_id("act"), reason="same callback, other line")
        assert len(reads) == 2  # the pre-insert check, then the read after the violation
        assert not second.created
        assert second.escalation.id == first.escalation.id
        assert count(a, "escalations") == 1
        assert count(a, "idempotency_keys") == 1  # the loser wrote nothing
    finally:
        a.close()
        b.close()


def test_unrelated_integrity_error_is_not_swallowed(conn, monkeypatch):
    def broken_insert(c, escalation):
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(repo, "insert_escalation", broken_insert)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        escalate(conn, new_id("act"))
    assert count(conn, "escalations") == 0
