"""M1b: mock EHR operations — identity, patients, booking, cancel, reschedule."""

from __future__ import annotations

from datetime import date

import pytest

from care_agent.ehr import repository as repo
from care_agent.ehr import service
from care_agent.ehr.service import EHRError, ErrorCode
from ehr_data import (
    NOW,
    PROVIDER_2_ID,
    PROVIDER_ID,
    SERVICE_ID,
    SLOT_1,
    SLOT_2,
    SLOT_3,
    SLOT_PAST,
    make_appointment,
    make_patient,
)

MARIA_DOB = date(1985, 3, 14)


def add_patient(conn, **overrides):
    patient = make_patient(**overrides)
    repo.insert_patient(conn, patient)
    return patient


def patient_count(conn) -> int:
    return conn.execute("SELECT count(*) FROM patients").fetchone()[0]


def appointment_count(conn) -> int:
    return conn.execute("SELECT count(*) FROM appointments").fetchone()[0]


def book(conn, patient_id, slot=SLOT_1):
    return service.book_appointment(conn, patient_id, SERVICE_ID, slot[0], now=NOW)


def assert_error(exc_info, code: ErrorCode) -> None:
    assert exc_info.value.code == code, str(exc_info.value)


# --- Identity resolution ---------------------------------------------------------


@pytest.mark.parametrize(
    "phones",
    [
        [("+15550100001",)],  # unique phone match
        [("+15550100001",), ("+15550100001",)],  # shared phone
        [()],  # phone not on file
    ],
)
def test_phone_without_name_and_dob_does_not_verify_identity(conn, phones):
    for index, patient_phones in enumerate(phones):
        add_patient(conn, first_name=f"Person{index}", phones=patient_phones)
    result = service.resolve_identity(conn, phone="+15550100001")
    assert result.status == "verification_required"
    assert result.patient is None
    assert result.candidate_count == 0  # nothing about phone holders is revealed


@pytest.mark.parametrize(
    "details",
    [
        {"last_name": "Garcia", "dob": MARIA_DOB},  # no first name
        {"first_name": "Maria", "last_name": "  ", "dob": MARIA_DOB},  # blank last name
        {"first_name": "Maria", "last_name": "Garcia"},  # no DOB
    ],
)
def test_incomplete_details_require_verification(conn, details):
    add_patient(conn)
    result = service.resolve_identity(conn, phone="+15550100001", **details)
    assert result.status == "verification_required"
    assert result.patient is None


def test_phone_confirmed_by_name_and_dob_ignores_phone_formatting(conn):
    maria = add_patient(conn)
    result = service.resolve_identity(
        conn, phone="+1 (555) 010-0001", first_name="Maria", last_name="Garcia", dob=MARIA_DOB
    )
    assert result.status == "matched"
    assert result.patient == maria
    assert result.method == "phone+name_dob"


def test_unknown_phone_falls_back_to_name_and_dob_without_creating_a_record(conn):
    # F3: existing patient calling from a number that is not on her record.
    maria = add_patient(conn)
    result = service.resolve_identity(
        conn, phone="+15559999999", first_name="maria", last_name="GARCIA", dob=MARIA_DOB
    )
    assert result.status == "matched"
    assert result.patient == maria
    assert result.method == "name_dob"
    assert patient_count(conn) == 1


def test_spouse_phone_resolves_to_the_caller_not_the_phone_owner(conn):
    # F3: the phone belongs to her husband, who is also a patient.
    maria = add_patient(conn, phones=())
    add_patient(conn, first_name="Luis", dob=date(1983, 7, 2), phones=("+15550100002",))
    result = service.resolve_identity(
        conn, phone="+15550100002", first_name="Maria", last_name="Garcia", dob=MARIA_DOB
    )
    assert result.status == "matched"
    assert result.patient == maria
    assert result.method == "name_dob"
    assert patient_count(conn) == 2


def test_name_dob_not_on_file_is_not_found_and_creates_nothing(conn):
    add_patient(conn)
    result = service.resolve_identity(
        conn, phone="+15550100001", first_name="Ana", last_name="Silva", dob=date(1990, 1, 2)
    )
    assert result.status == "not_found"
    assert patient_count(conn) == 1


def test_name_matching_folds_non_ascii_case(conn):
    jose = add_patient(conn, first_name="José", last_name="Núñez", phones=())
    result = service.resolve_identity(conn, first_name="JOSÉ", last_name="núñez", dob=MARIA_DOB)
    assert result.patient == jose


@pytest.mark.parametrize(
    ("record_phones", "caller_phone"),
    [
        (((), ()), None),  # no phone given
        ((("+15550100001",), ("+15550100002",)), "+15559999999"),  # phone matches neither
        ((("+15550100001",), ("+15550100001",)), "+15550100001"),  # phone matches both
    ],
)
def test_duplicate_name_and_dob_records_stay_ambiguous(conn, record_phones, caller_phone):
    for phones in record_phones:
        add_patient(conn, phones=phones)
    result = service.resolve_identity(
        conn, phone=caller_phone, first_name="Maria", last_name="Garcia", dob=MARIA_DOB
    )
    assert result.status == "ambiguous"
    assert result.candidate_count == 2
    assert result.patient is None


def test_phone_hint_separates_duplicate_name_and_dob_records(conn):
    add_patient(conn, phones=())
    holder = add_patient(conn, phones=("+15550100001",))
    result = service.resolve_identity(
        conn, phone="+15550100001", first_name="Maria", last_name="Garcia", dob=MARIA_DOB
    )
    assert result.status == "matched"
    assert result.patient == holder
    assert result.method == "phone+name_dob"


# --- Patient creation ------------------------------------------------------------


def test_create_patient_normalises_phone_and_reads_back(conn):
    patient = service.create_patient(
        conn, "Ana", "Silva", date(1990, 1, 2), phone="+1 555 010 0003", now=NOW
    )
    assert patient.id.startswith("pat_")
    assert patient.phones == ("+15550100003",)
    assert repo.get_patient(conn, patient.id) == patient


def test_create_patient_refuses_possible_duplicate(conn):
    add_patient(conn)
    with pytest.raises(EHRError) as exc_info:
        service.create_patient(conn, " maria ", "garcia", MARIA_DOB, phone=None, now=NOW)
    assert_error(exc_info, ErrorCode.POSSIBLE_DUPLICATE)
    assert patient_count(conn) == 1


def test_create_patient_rejects_invalid_fields(conn):
    with pytest.raises(EHRError) as exc_info:
        service.create_patient(conn, "  ", "Silva", date(1990, 1, 2), phone=None, now=NOW)
    assert_error(exc_info, ErrorCode.INVALID_ARGUMENT)
    assert patient_count(conn) == 0


# --- Booking ---------------------------------------------------------------------


def test_book_appointment(conn):
    maria = add_patient(conn)
    appointment = book(conn, maria.id)
    assert appointment.status == "booked"
    assert appointment.provider_id == PROVIDER_ID  # taken from the slot
    assert appointment.slot_id == SLOT_1[0]
    assert appointment.start_at.isoformat() == SLOT_1[1]
    assert appointment.version == 1
    assert repo.list_appointments_for_patient(conn, maria.id) == [appointment]


@pytest.mark.parametrize(
    ("patient_id", "service_id", "slot_id"),
    [
        ("svc_cleaning", SERVICE_ID, SLOT_1[0]),  # service ID as patient ID
        ("pat_maria", "slot_tue1000", SLOT_1[0]),  # slot ID as service ID
        ("pat_maria", SERVICE_ID, "apt_123"),  # appointment ID as slot ID
    ],
)
def test_book_rejects_wrong_id_types(conn, patient_id, service_id, slot_id):
    with pytest.raises(EHRError) as exc_info:
        service.book_appointment(conn, patient_id, service_id, slot_id, now=NOW)
    assert_error(exc_info, ErrorCode.INVALID_ID)
    assert appointment_count(conn) == 0


@pytest.mark.parametrize("missing", ["patient", "service", "slot"])
def test_book_rejects_missing_records(conn, missing):
    maria = add_patient(conn)
    args = {"patient_id": maria.id, "service_id": SERVICE_ID, "slot_id": SLOT_1[0]}
    args[f"{missing}_id"] = {"patient": "pat_nobody", "service": "svc_none", "slot": "slot_none"}[
        missing
    ]
    with pytest.raises(EHRError) as exc_info:
        service.book_appointment(conn, now=NOW, **args)
    assert_error(exc_info, ErrorCode.NOT_FOUND)
    assert appointment_count(conn) == 0


def test_book_rejects_already_booked_slot(conn):
    maria, ana = add_patient(conn), add_patient(conn, first_name="Ana")
    book(conn, maria.id)
    with pytest.raises(EHRError) as exc_info:
        book(conn, ana.id)
    assert_error(exc_info, ErrorCode.SLOT_UNAVAILABLE)
    assert appointment_count(conn) == 1


def test_book_rejects_past_slot(conn):
    maria = add_patient(conn)
    with pytest.raises(EHRError) as exc_info:
        book(conn, maria.id, slot=SLOT_PAST)
    assert_error(exc_info, ErrorCode.SLOT_UNAVAILABLE)


def test_cancelled_slot_can_be_booked_again(conn):
    maria, ana = add_patient(conn), add_patient(conn, first_name="Ana")
    service.cancel_appointment(conn, book(conn, maria.id).id, now=NOW)
    assert book(conn, ana.id).status == "booked"


# --- Cancellation ----------------------------------------------------------------


def test_cancel_appointment(conn):
    maria = add_patient(conn)
    booked = book(conn, maria.id)
    cancelled = service.cancel_appointment(conn, booked.id, now=NOW, reason="feeling better")
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at == NOW
    assert cancelled.cancel_reason == "feeling better"
    assert cancelled.version == booked.version + 1
    assert repo.get_appointment(conn, booked.id) == cancelled


def test_cancel_with_service_id_is_rejected_and_changes_nothing(conn):
    # F4: a service ID where the appointment ID belongs.
    maria = add_patient(conn)
    booked = book(conn, maria.id)
    with pytest.raises(EHRError) as exc_info:
        service.cancel_appointment(conn, SERVICE_ID, now=NOW)
    assert_error(exc_info, ErrorCode.INVALID_ID)
    assert repo.get_appointment(conn, booked.id) == booked


def test_cancel_missing_appointment(conn):
    with pytest.raises(EHRError) as exc_info:
        service.cancel_appointment(conn, "apt_nothere", now=NOW)
    assert_error(exc_info, ErrorCode.NOT_FOUND)


def test_cancel_already_cancelled_appointment(conn):
    # F5: the appointment was cancelled earlier (e.g. directly in the EHR).
    maria = add_patient(conn)
    booked = book(conn, maria.id)
    first = service.cancel_appointment(conn, booked.id, now=NOW)
    with pytest.raises(EHRError) as exc_info:
        service.cancel_appointment(conn, booked.id, now=NOW)
    assert_error(exc_info, ErrorCode.ALREADY_CANCELLED)
    assert repo.get_appointment(conn, booked.id) == first


def test_cancel_past_appointment_is_rejected(conn):
    maria = add_patient(conn)
    past = make_appointment(maria.id, slot=SLOT_PAST)
    repo.insert_appointment(conn, past)
    with pytest.raises(EHRError) as exc_info:
        service.cancel_appointment(conn, past.id, now=NOW)
    assert_error(exc_info, ErrorCode.APPOINTMENT_IN_PAST)
    assert repo.get_appointment(conn, past.id) == past


# --- Rescheduling ----------------------------------------------------------------


def test_reschedule_moves_appointment_and_frees_old_slot(conn):
    maria, ana = add_patient(conn), add_patient(conn, first_name="Ana")
    booked = book(conn, maria.id)
    moved = service.reschedule_appointment(conn, booked.id, SLOT_3[0], now=NOW)

    assert moved.id == booked.id
    assert moved.status == "booked"
    assert moved.slot_id == SLOT_3[0]
    assert moved.provider_id == PROVIDER_2_ID  # follows the new slot
    assert moved.start_at.isoformat() == SLOT_3[1]
    assert moved.version == booked.version + 1
    assert book(conn, ana.id, slot=SLOT_1).status == "booked"  # old slot is free


@pytest.mark.parametrize(
    ("new_slot_id", "code"),
    [
        (SLOT_2[0], ErrorCode.SLOT_UNAVAILABLE),  # taken by another patient
        (SLOT_PAST[0], ErrorCode.SLOT_UNAVAILABLE),
        ("slot_none", ErrorCode.NOT_FOUND),
        (SERVICE_ID, ErrorCode.INVALID_ID),
        (SLOT_1[0], ErrorCode.INVALID_ARGUMENT),  # same slot
    ],
)
def test_failed_reschedule_leaves_appointment_unchanged(conn, new_slot_id, code):
    maria, ana = add_patient(conn), add_patient(conn, first_name="Ana")
    booked = book(conn, maria.id)
    book(conn, ana.id, slot=SLOT_2)
    with pytest.raises(EHRError) as exc_info:
        service.reschedule_appointment(conn, booked.id, new_slot_id, now=NOW)
    assert_error(exc_info, code)
    assert repo.get_appointment(conn, booked.id) == booked


def test_reschedule_is_atomic_when_slot_is_taken_after_the_check(conn, monkeypatch):
    # Simulate a race: the availability check says free, but another booking
    # holds the slot. The database rejects the move; nothing changes.
    maria, ana = add_patient(conn), add_patient(conn, first_name="Ana")
    booked = book(conn, maria.id)
    book(conn, ana.id, slot=SLOT_2)
    monkeypatch.setattr(repo, "slot_is_booked", lambda conn, slot_id: False)
    with pytest.raises(EHRError) as exc_info:
        service.reschedule_appointment(conn, booked.id, SLOT_2[0], now=NOW)
    assert_error(exc_info, ErrorCode.SLOT_UNAVAILABLE)
    assert repo.get_appointment(conn, booked.id) == booked


def test_reschedule_cancelled_appointment_is_rejected(conn):
    maria = add_patient(conn)
    cancelled = service.cancel_appointment(conn, book(conn, maria.id).id, now=NOW)
    with pytest.raises(EHRError) as exc_info:
        service.reschedule_appointment(conn, cancelled.id, SLOT_3[0], now=NOW)
    assert_error(exc_info, ErrorCode.ALREADY_CANCELLED)
    assert repo.get_appointment(conn, cancelled.id) == cancelled
