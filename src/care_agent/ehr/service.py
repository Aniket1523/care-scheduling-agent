"""Mock EHR business operations: identity resolution, patients, booking,
cancellation and rescheduling.

Every operation takes ``now`` explicitly (injected clock) and either returns
the record as read back from the database or raises ``EHRError`` with a
machine-readable ``code``. Raw IDs are validated here, so a service ID passed
where an appointment ID belongs (F4) fails with ``INVALID_ID`` before any
lookup.

Not here yet, by design: idempotency keys, fault injection, retries and
optimistic-concurrency checks (later milestones).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from care_agent.ehr import repository as repo
from care_agent.ehr.models import Appointment, Patient
from care_agent.ids import AppointmentId, PatientId, ServiceId, SlotId, new_id


class ErrorCode(StrEnum):
    INVALID_ID = "INVALID_ID"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    SLOT_UNAVAILABLE = "SLOT_UNAVAILABLE"
    ALREADY_CANCELLED = "ALREADY_CANCELLED"
    APPOINTMENT_IN_PAST = "APPOINTMENT_IN_PAST"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"


class EHRError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- Validation helpers ----------------------------------------------------------

_ID_TYPES: dict[str, tuple[TypeAdapter[str], str]] = {
    "patient_id": (TypeAdapter(PatientId), "pat_"),
    "service_id": (TypeAdapter(ServiceId), "svc_"),
    "slot_id": (TypeAdapter(SlotId), "slot_"),
    "appointment_id": (TypeAdapter(AppointmentId), "apt_"),
}


def _check_id(field: str, value: str) -> str:
    adapter, prefix = _ID_TYPES[field]
    try:
        return adapter.validate_python(value)
    except ValidationError:
        raise EHRError(
            ErrorCode.INVALID_ID, f"{field} must be an ID starting with '{prefix}', got {value!r}"
        ) from None


_PHONE_SEPARATORS = re.compile(r"[\s\-().]")


def normalize_phone(raw: str) -> str:
    """Remove spaces, dashes, dots and brackets: '+1 (555) 010-0001' -> '+15550100001'."""
    return _PHONE_SEPARATORS.sub("", raw)


def _same_name(patient: Patient, first_name: str, last_name: str) -> bool:
    return (
        patient.first_name.casefold() == first_name.strip().casefold()
        and patient.last_name.casefold() == last_name.strip().casefold()
    )


# --- Identity resolution ---------------------------------------------------------


MatchMethod = Literal["phone+name_dob", "name_dob"]


@dataclass(frozen=True)
class IdentityResult:
    """Outcome of an identity lookup.

    ``verification_required`` means first name, last name or date of birth is
    missing: nothing was looked up, and a phone number alone never verifies
    anyone. For ``ambiguous`` only the number of candidates is returned, never
    their details: the caller must not be read another patient's information.
    """

    status: Literal["matched", "not_found", "ambiguous", "verification_required"]
    patient: Patient | None = None
    method: MatchMethod | None = None
    candidate_count: int = 0


def resolve_identity(
    conn: sqlite3.Connection,
    phone: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    dob: date | None = None,
) -> IdentityResult:
    """Verify the caller's identity. Never creates a record.

    Identity is established by first name, last name and date of birth. The
    caller's phone number is only a hint: among patients who match on name and
    DOB, one who also has this phone is preferred (this can separate duplicate
    records). If no phone holder matches (e.g. calling from a spouse's phone,
    F3), the name + DOB search decides.
    """
    if first_name is None or last_name is None or dob is None:
        return IdentityResult(status="verification_required")
    if not first_name.strip() or not last_name.strip():
        return IdentityResult(status="verification_required")

    phone_matches = repo.find_patients_by_phone(conn, normalize_phone(phone)) if phone else []
    confirmed = [p for p in phone_matches if _same_person(p, first_name, last_name, dob)]
    if confirmed:
        return _result(confirmed, "phone+name_dob")

    return _result(_find_by_name_dob(conn, first_name, last_name, dob), "name_dob")


def _find_by_name_dob(
    conn: sqlite3.Connection, first_name: str, last_name: str, dob: date
) -> list[Patient]:
    return [p for p in repo.find_patients_by_dob(conn, dob) if _same_name(p, first_name, last_name)]


def _same_person(patient: Patient, first_name: str, last_name: str, dob: date) -> bool:
    return patient.dob == dob and _same_name(patient, first_name, last_name)


def _result(candidates: list[Patient], method: MatchMethod) -> IdentityResult:
    if not candidates:
        return IdentityResult(status="not_found")
    if len(candidates) > 1:
        return IdentityResult(status="ambiguous", candidate_count=len(candidates))
    return IdentityResult(status="matched", patient=candidates[0], method=method, candidate_count=1)


# --- Patients --------------------------------------------------------------------


def create_patient(
    conn: sqlite3.Connection,
    first_name: str,
    last_name: str,
    dob: date,
    phone: str | None,
    now: datetime,
) -> Patient:
    """Register a new patient. Refuses if a patient with the same name and DOB exists.

    Separate from identity lookup on purpose: a failed lookup must never create
    a record by itself (F3).
    """
    if _find_by_name_dob(conn, first_name, last_name, dob):
        raise EHRError(
            ErrorCode.POSSIBLE_DUPLICATE,
            "a patient with this name and date of birth already exists",
        )
    try:
        patient = Patient(
            id=new_id("pat"),
            first_name=first_name,
            last_name=last_name,
            dob=dob,
            phones=(normalize_phone(phone),) if phone else (),
            created_at=now,
        )
    except ValidationError as exc:
        fields = ", ".join(str(err["loc"][0]) for err in exc.errors())
        raise EHRError(ErrorCode.INVALID_ARGUMENT, f"invalid patient fields: {fields}") from None
    repo.insert_patient(conn, patient)
    return _read_back_patient(conn, patient.id)


def _read_back_patient(conn: sqlite3.Connection, patient_id: str) -> Patient:
    patient = repo.get_patient(conn, patient_id)
    assert patient is not None, "patient missing immediately after insert"
    return patient


# --- Appointments ----------------------------------------------------------------


def book_appointment(
    conn: sqlite3.Connection,
    patient_id: str,
    service_id: str,
    slot_id: str,
    now: datetime,
) -> Appointment:
    """Book a free, future slot for a patient. The provider comes from the slot."""
    patient_id = _check_id("patient_id", patient_id)
    service_id = _check_id("service_id", service_id)
    slot_id = _check_id("slot_id", slot_id)

    if repo.get_patient(conn, patient_id) is None:
        raise EHRError(ErrorCode.NOT_FOUND, f"patient {patient_id} not found")
    if repo.get_service(conn, service_id) is None:
        raise EHRError(ErrorCode.NOT_FOUND, f"service {service_id} not found")
    slot = repo.get_slot(conn, slot_id)
    if slot is None:
        raise EHRError(ErrorCode.NOT_FOUND, f"slot {slot_id} not found")
    _require_free_future_slot(conn, slot.id, slot.start_at, now)

    appointment = Appointment(
        id=new_id("apt"),
        patient_id=patient_id,
        provider_id=slot.provider_id,
        service_id=service_id,
        slot_id=slot.id,
        start_at=slot.start_at,
        end_at=slot.end_at,
        status="booked",
        created_at=now,
        updated_at=now,
    )
    try:
        repo.insert_appointment(conn, appointment)
    except sqlite3.IntegrityError:
        # Another booking took the slot between the check and the insert.
        raise EHRError(ErrorCode.SLOT_UNAVAILABLE, f"slot {slot_id} is already booked") from None
    return _read_back_appointment(conn, appointment.id)


def cancel_appointment(
    conn: sqlite3.Connection,
    appointment_id: str,
    now: datetime,
    reason: str | None = None,
) -> Appointment:
    appointment = _get_booked_future_appointment(conn, appointment_id, now)
    if not repo.mark_cancelled(conn, appointment.id, reason, now):
        raise EHRError(ErrorCode.ALREADY_CANCELLED, f"appointment {appointment.id} is cancelled")
    return _read_back_appointment(conn, appointment.id)


def reschedule_appointment(
    conn: sqlite3.Connection,
    appointment_id: str,
    new_slot_id: str,
    now: datetime,
) -> Appointment:
    """Move a booked appointment to a new slot as one atomic update.

    On any failure the appointment is left exactly as it was: still booked,
    in its original slot.
    """
    appointment = _get_booked_future_appointment(conn, appointment_id, now)
    new_slot_id = _check_id("slot_id", new_slot_id)
    if new_slot_id == appointment.slot_id:
        raise EHRError(ErrorCode.INVALID_ARGUMENT, "the new slot is the current slot")
    slot = repo.get_slot(conn, new_slot_id)
    if slot is None:
        raise EHRError(ErrorCode.NOT_FOUND, f"slot {new_slot_id} not found")
    _require_free_future_slot(conn, slot.id, slot.start_at, now)

    try:
        moved = repo.move_to_slot(conn, appointment.id, slot, now)
    except sqlite3.IntegrityError:
        raise EHRError(ErrorCode.SLOT_UNAVAILABLE, f"slot {slot.id} is already booked") from None
    if not moved:
        raise EHRError(ErrorCode.ALREADY_CANCELLED, f"appointment {appointment.id} is cancelled")
    return _read_back_appointment(conn, appointment.id)


def _get_booked_future_appointment(
    conn: sqlite3.Connection, appointment_id: str, now: datetime
) -> Appointment:
    appointment_id = _check_id("appointment_id", appointment_id)
    appointment = repo.get_appointment(conn, appointment_id)
    if appointment is None:
        raise EHRError(ErrorCode.NOT_FOUND, f"appointment {appointment_id} not found")
    if appointment.status == "cancelled":
        raise EHRError(ErrorCode.ALREADY_CANCELLED, f"appointment {appointment_id} is cancelled")
    if appointment.start_at <= now:
        raise EHRError(
            ErrorCode.APPOINTMENT_IN_PAST, f"appointment {appointment_id} has already started"
        )
    return appointment


def _require_free_future_slot(
    conn: sqlite3.Connection, slot_id: str, start_at: datetime, now: datetime
) -> None:
    if start_at <= now:
        raise EHRError(ErrorCode.SLOT_UNAVAILABLE, f"slot {slot_id} is in the past")
    if repo.slot_is_booked(conn, slot_id):
        raise EHRError(ErrorCode.SLOT_UNAVAILABLE, f"slot {slot_id} is already booked")


def _read_back_appointment(conn: sqlite3.Connection, appointment_id: str) -> Appointment:
    appointment = repo.get_appointment(conn, appointment_id)
    assert appointment is not None, "appointment missing immediately after write"
    return appointment
