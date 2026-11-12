"""Mock EHR business operations: identity resolution, patients, booking,
cancellation, rescheduling and escalation.

Every operation takes ``now`` explicitly (injected clock) and either returns
the record as read back from the database or raises ``EHRError`` with a
machine-readable ``code`` (or ``EHRTimeout``). Raw IDs are validated here, so
a service ID passed where an appointment ID belongs (F4) fails with
``INVALID_ID`` before any lookup.

Reliability:

* Booking and escalation take a caller-provided ``action_id``. The action is
  recorded in the same transaction as the record it creates; repeating it
  returns the original record instead of creating another, and reusing it
  with different arguments is an ``IDEMPOTENCY_CONFLICT``.
* Cancel and reschedule take ``expected_version`` (the version the caller
  read). The check is part of the UPDATE, so a change made elsewhere since
  that read (F5) is never overwritten: ``STALE_VERSION``.
* An optional ``FaultPlan`` makes a write time out or fail, before or after
  its commit, deterministically.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from care_agent.ehr import repository as repo
from care_agent.ehr.faults import FaultMode, FaultPlan
from care_agent.ehr.models import Appointment, Escalation, Patient
from care_agent.ehr.repository import IdempotencyRecord
from care_agent.ids import ActionId, AppointmentId, PatientId, ServiceId, SlotId, new_id


class ErrorCode(StrEnum):
    INVALID_ID = "INVALID_ID"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    SLOT_UNAVAILABLE = "SLOT_UNAVAILABLE"
    ALREADY_CANCELLED = "ALREADY_CANCELLED"
    APPOINTMENT_IN_PAST = "APPOINTMENT_IN_PAST"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    STALE_VERSION = "STALE_VERSION"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class EHRError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class EHRTimeout(TimeoutError):
    """The EHR did not answer in time. The caller cannot tell whether the write happened."""


# --- Validation helpers ----------------------------------------------------------

_ID_TYPES: dict[str, tuple[TypeAdapter[str], str]] = {
    "patient_id": (TypeAdapter(PatientId), "pat_"),
    "service_id": (TypeAdapter(ServiceId), "svc_"),
    "slot_id": (TypeAdapter(SlotId), "slot_"),
    "appointment_id": (TypeAdapter(AppointmentId), "apt_"),
    "action_id": (TypeAdapter(ActionId), "act_"),
}


def check_id(field: str, value: str) -> str:
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
    with conn:
        repo.insert_patient(conn, patient)
    return _read_back_patient(conn, patient.id)


def _read_back_patient(conn: sqlite3.Connection, patient_id: str) -> Patient:
    patient = repo.get_patient(conn, patient_id)
    assert patient is not None, "patient missing immediately after insert"
    return patient


# --- Reliable writes -------------------------------------------------------------


def _run_write[T](
    conn: sqlite3.Connection, operation: str, faults: FaultPlan | None, body: Callable[[], T]
) -> T:
    """Run ``body`` in one transaction, applying the planned fault, if any.

    A fault before commit is raised inside the transaction, so everything the
    body wrote is rolled back. Faults after commit are raised once the data is
    durable. Both timeouts carry the same message: like a real client, the
    caller cannot tell them apart.
    """
    fault = faults.next_fault(operation) if faults else None
    with conn:
        result = body()
        if fault is FaultMode.TIMEOUT_BEFORE_COMMIT:
            raise EHRTimeout(f"{operation} timed out")
    if fault is FaultMode.TIMEOUT_AFTER_COMMIT:
        raise EHRTimeout(f"{operation} timed out")
    if fault is FaultMode.ERROR_AFTER_COMMIT:
        raise EHRError(ErrorCode.INTERNAL_ERROR, f"{operation} failed with an internal error")
    return result


def _request_hash(request: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


def _previous_result(
    conn: sqlite3.Connection, action_id: str, operation: str, request_hash: str
) -> str | None:
    """ID of the record this action already created, or None if it is new."""
    record = repo.get_idempotency_record(conn, action_id)
    if record is None:
        return None
    if record.operation != operation or record.request_hash != request_hash:
        raise EHRError(
            ErrorCode.IDEMPOTENCY_CONFLICT,
            f"action {action_id} was already used for a different request; "
            "a new action needs a new action_id",
        )
    return record.result_id


# --- Appointments ----------------------------------------------------------------


def book_appointment(
    conn: sqlite3.Connection,
    patient_id: str,
    service_id: str,
    slot_id: str,
    *,
    action_id: str,
    now: datetime,
    faults: FaultPlan | None = None,
) -> Appointment:
    """Book a free, future slot for a patient. The provider comes from the slot.

    Repeating the call with the same ``action_id`` and arguments returns the
    appointment the first call created (as it is now), without booking again.
    """
    patient_id = check_id("patient_id", patient_id)
    service_id = check_id("service_id", service_id)
    slot_id = check_id("slot_id", slot_id)
    action_id = check_id("action_id", action_id)
    operation = "book_appointment"
    request_hash = _request_hash(
        {"patient_id": patient_id, "service_id": service_id, "slot_id": slot_id}
    )

    def body() -> Appointment:
        previous = _previous_result(conn, action_id, operation, request_hash)
        if previous is not None:
            return _read_back_appointment(conn, previous)

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
            raise EHRError(
                ErrorCode.SLOT_UNAVAILABLE, f"slot {slot_id} is already booked"
            ) from None
        repo.insert_idempotency_record(
            conn, IdempotencyRecord(action_id, operation, request_hash, appointment.id), now
        )
        return _read_back_appointment(conn, appointment.id)

    return _run_write(conn, operation, faults, body)


def cancel_appointment(
    conn: sqlite3.Connection,
    appointment_id: str,
    *,
    expected_version: int,
    now: datetime,
    reason: str | None = None,
    faults: FaultPlan | None = None,
) -> Appointment:
    """Cancel a booked, future appointment that is still at ``expected_version``."""
    appointment_id = check_id("appointment_id", appointment_id)

    def body() -> Appointment:
        appointment = _get_current_booked_future(conn, appointment_id, expected_version, now)
        if not repo.mark_cancelled(conn, appointment.id, expected_version, reason, now):
            raise _stale(appointment.id)
        return _read_back_appointment(conn, appointment.id)

    return _run_write(conn, "cancel_appointment", faults, body)


def reschedule_appointment(
    conn: sqlite3.Connection,
    appointment_id: str,
    new_slot_id: str,
    *,
    expected_version: int,
    now: datetime,
    faults: FaultPlan | None = None,
) -> Appointment:
    """Move a booked appointment to a new slot as one atomic update.

    On any failure the appointment is left exactly as it was: still booked,
    in its original slot.
    """
    appointment_id = check_id("appointment_id", appointment_id)
    new_slot_id = check_id("slot_id", new_slot_id)

    def body() -> Appointment:
        appointment = _get_current_booked_future(conn, appointment_id, expected_version, now)
        if new_slot_id == appointment.slot_id:
            raise EHRError(ErrorCode.INVALID_ARGUMENT, "the new slot is the current slot")
        slot = repo.get_slot(conn, new_slot_id)
        if slot is None:
            raise EHRError(ErrorCode.NOT_FOUND, f"slot {new_slot_id} not found")
        _require_free_future_slot(conn, slot.id, slot.start_at, now)
        try:
            moved = repo.move_to_slot(conn, appointment.id, expected_version, slot, now)
        except sqlite3.IntegrityError:
            raise EHRError(
                ErrorCode.SLOT_UNAVAILABLE, f"slot {slot.id} is already booked"
            ) from None
        if not moved:
            raise _stale(appointment.id)
        return _read_back_appointment(conn, appointment.id)

    return _run_write(conn, "reschedule_appointment", faults, body)


def _get_current_booked_future(
    conn: sqlite3.Connection, appointment_id: str, expected_version: int, now: datetime
) -> Appointment:
    """Load the appointment and check, in order: it exists, it is unchanged since
    the caller read it, it is booked, and it has not started."""
    appointment = repo.get_appointment(conn, appointment_id)
    if appointment is None:
        raise EHRError(ErrorCode.NOT_FOUND, f"appointment {appointment_id} not found")
    if appointment.version != expected_version:
        raise _stale(appointment_id)
    if appointment.status == "cancelled":
        raise EHRError(ErrorCode.ALREADY_CANCELLED, f"appointment {appointment_id} is cancelled")
    if appointment.start_at <= now:
        raise EHRError(
            ErrorCode.APPOINTMENT_IN_PAST, f"appointment {appointment_id} has already started"
        )
    return appointment


def _stale(appointment_id: str) -> EHRError:
    return EHRError(
        ErrorCode.STALE_VERSION,
        f"appointment {appointment_id} changed since it was read; read it again",
    )


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


# --- Escalations -----------------------------------------------------------------


def create_escalation(
    conn: sqlite3.Connection,
    call_id: str,
    reason: str,
    *,
    action_id: str,
    now: datetime,
    patient_id: str | None = None,
    faults: FaultPlan | None = None,
) -> Escalation:
    """Ask clinic staff to follow up on this call.

    Idempotent per ``action_id``. A call has at most one open escalation: a new
    action for a call that already has one returns that escalation rather than
    opening a second (F2).
    """
    action_id = check_id("action_id", action_id)
    if patient_id is not None:
        patient_id = check_id("patient_id", patient_id)
    operation = "create_escalation"
    request_hash = _request_hash(
        {"call_id": call_id.strip(), "patient_id": patient_id, "reason": reason.strip()}
    )

    def body() -> Escalation:
        previous = _previous_result(conn, action_id, operation, request_hash)
        if previous is not None:
            return _read_back_escalation(conn, previous)

        if patient_id is not None and repo.get_patient(conn, patient_id) is None:
            raise EHRError(ErrorCode.NOT_FOUND, f"patient {patient_id} not found")
        escalation = repo.find_open_escalation(conn, call_id.strip())
        if escalation is None:
            try:
                escalation = Escalation(
                    id=new_id("esc"),
                    call_id=call_id,
                    patient_id=patient_id,
                    reason=reason,
                    created_at=now,
                )
            except ValidationError as exc:
                fields = ", ".join(str(err["loc"][0]) for err in exc.errors())
                raise EHRError(
                    ErrorCode.INVALID_ARGUMENT, f"invalid escalation fields: {fields}"
                ) from None
            repo.insert_escalation(conn, escalation)
        repo.insert_idempotency_record(
            conn, IdempotencyRecord(action_id, operation, request_hash, escalation.id), now
        )
        return _read_back_escalation(conn, escalation.id)

    return _run_write(conn, operation, faults, body)


def _read_back_escalation(conn: sqlite3.Connection, escalation_id: str) -> Escalation:
    escalation = repo.get_escalation(conn, escalation_id)
    assert escalation is not None, "escalation missing immediately after write"
    return escalation
