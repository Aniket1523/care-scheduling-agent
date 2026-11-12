"""Persistence functions for the mock EHR.

These functions store and load data. They contain no scheduling rules
(availability, whether something may be cancelled); those live in
``care_agent.ehr.service``.

Transactions: write functions never commit. The caller owns the transaction
(``with conn:``), so several writes - e.g. an appointment and its idempotency
record - commit or roll back together.

Constraint violations surface as ``sqlite3.IntegrityError``. Lookups of a
missing record return ``None`` (or an empty list).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime

from care_agent.ehr.models import Appointment, Escalation, Patient, Service, Slot

_APPOINTMENT_COLUMNS = (
    "id, patient_id, provider_id, service_id, slot_id, start_at, end_at, status, version, "
    "created_at, updated_at, cancelled_at, cancel_reason"
)
_ESCALATION_COLUMNS = "id, call_id, patient_id, reason, status, created_at"


def to_db_time(value: datetime) -> str:
    """Store an aware datetime as a UTC ISO-8601 string with second precision."""
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _optional_time(value: datetime | None) -> str | None:
    return None if value is None else to_db_time(value)


# --- Patients --------------------------------------------------------------------


def insert_patient(conn: sqlite3.Connection, patient: Patient) -> None:
    """Insert a patient and their phone numbers (caller owns the transaction)."""
    conn.execute(
        "INSERT INTO patients (id, first_name, last_name, dob, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            patient.id,
            patient.first_name,
            patient.last_name,
            patient.dob.isoformat(),
            to_db_time(patient.created_at),
        ),
    )
    conn.executemany(
        "INSERT INTO patient_phones (patient_id, phone) VALUES (?, ?)",
        [(patient.id, phone) for phone in patient.phones],
    )


def get_patient(conn: sqlite3.Connection, patient_id: str) -> Patient | None:
    row = conn.execute(
        "SELECT id, first_name, last_name, dob, created_at FROM patients WHERE id = ?",
        (patient_id,),
    ).fetchone()
    if row is None:
        return None
    phones = conn.execute(
        "SELECT phone FROM patient_phones WHERE patient_id = ? ORDER BY phone",
        (patient_id,),
    ).fetchall()
    return Patient.model_validate({**dict(row), "phones": tuple(p["phone"] for p in phones)})


def find_patients_by_phone(conn: sqlite3.Connection, phone: str) -> list[Patient]:
    rows = conn.execute(
        "SELECT patient_id FROM patient_phones WHERE phone = ? ORDER BY patient_id", (phone,)
    ).fetchall()
    return [p for row in rows if (p := get_patient(conn, row["patient_id"])) is not None]


def find_patients_by_dob(conn: sqlite3.Connection, dob: date) -> list[Patient]:
    """Candidates for name + date-of-birth matching.

    Names are compared in Python by the caller: SQLite's lower() only folds
    ASCII, so it would treat "García" and "GARCÍA" as different names.
    """
    rows = conn.execute(
        "SELECT id FROM patients WHERE dob = ? ORDER BY id", (dob.isoformat(),)
    ).fetchall()
    return [p for row in rows if (p := get_patient(conn, row["id"])) is not None]


# --- Reference data --------------------------------------------------------------


def get_service(conn: sqlite3.Connection, service_id: str) -> Service | None:
    row = conn.execute(
        "SELECT id, name, duration_min FROM services WHERE id = ?", (service_id,)
    ).fetchone()
    return None if row is None else Service.model_validate(dict(row))


def get_slot(conn: sqlite3.Connection, slot_id: str) -> Slot | None:
    row = conn.execute(
        "SELECT id, provider_id, start_at, end_at FROM slots WHERE id = ?", (slot_id,)
    ).fetchone()
    return None if row is None else Slot.model_validate(dict(row))


def slot_is_booked(conn: sqlite3.Connection, slot_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM appointments WHERE slot_id = ? AND status = 'booked'", (slot_id,)
    ).fetchone()
    return row is not None


# --- Appointments ----------------------------------------------------------------


def insert_appointment(conn: sqlite3.Connection, appointment: Appointment) -> None:
    conn.execute(
        f"INSERT INTO appointments ({_APPOINTMENT_COLUMNS}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            appointment.id,
            appointment.patient_id,
            appointment.provider_id,
            appointment.service_id,
            appointment.slot_id,
            to_db_time(appointment.start_at),
            to_db_time(appointment.end_at),
            appointment.status,
            appointment.version,
            to_db_time(appointment.created_at),
            to_db_time(appointment.updated_at),
            _optional_time(appointment.cancelled_at),
            appointment.cancel_reason,
        ),
    )


def get_appointment(conn: sqlite3.Connection, appointment_id: str) -> Appointment | None:
    row = conn.execute(
        f"SELECT {_APPOINTMENT_COLUMNS} FROM appointments WHERE id = ?",
        (appointment_id,),
    ).fetchone()
    return None if row is None else Appointment.model_validate(dict(row))


def list_appointments_for_patient(conn: sqlite3.Connection, patient_id: str) -> list[Appointment]:
    """All of a patient's appointments (booked and cancelled), earliest first."""
    rows = conn.execute(
        f"SELECT {_APPOINTMENT_COLUMNS} FROM appointments "
        "WHERE patient_id = ? ORDER BY start_at, id",
        (patient_id,),
    ).fetchall()
    return [Appointment.model_validate(dict(row)) for row in rows]


def mark_cancelled(
    conn: sqlite3.Connection,
    appointment_id: str,
    expected_version: int,
    reason: str | None,
    now: datetime,
) -> bool:
    """Cancel a booked appointment if it is still at ``expected_version``.

    The version check is part of the UPDATE itself, so a change made by anyone
    else since the caller's read can never be overwritten. Returns False if no
    row matched (stale version or no longer booked).
    """
    cursor = conn.execute(
        "UPDATE appointments SET status = 'cancelled', cancelled_at = ?, cancel_reason = ?, "
        "updated_at = ?, version = version + 1 "
        "WHERE id = ? AND status = 'booked' AND version = ?",
        (to_db_time(now), reason, to_db_time(now), appointment_id, expected_version),
    )
    return cursor.rowcount == 1


def move_to_slot(
    conn: sqlite3.Connection,
    appointment_id: str,
    expected_version: int,
    slot: Slot,
    now: datetime,
) -> bool:
    """Move a booked appointment at ``expected_version`` to another slot in one UPDATE.

    One statement is atomic: either the appointment moves completely (slot,
    provider, times, version) or nothing changes. If the new slot is already
    booked, the one-booking-per-slot index raises IntegrityError. Returns False
    if no row matched (stale version or no longer booked).
    """
    cursor = conn.execute(
        "UPDATE appointments SET slot_id = ?, provider_id = ?, start_at = ?, end_at = ?, "
        "updated_at = ?, version = version + 1 "
        "WHERE id = ? AND status = 'booked' AND version = ?",
        (
            slot.id,
            slot.provider_id,
            to_db_time(slot.start_at),
            to_db_time(slot.end_at),
            to_db_time(now),
            appointment_id,
            expected_version,
        ),
    )
    return cursor.rowcount == 1


# --- Escalations -----------------------------------------------------------------


def insert_escalation(conn: sqlite3.Connection, escalation: Escalation) -> None:
    conn.execute(
        f"INSERT INTO escalations ({_ESCALATION_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
        (
            escalation.id,
            escalation.call_id,
            escalation.patient_id,
            escalation.reason,
            escalation.status,
            to_db_time(escalation.created_at),
        ),
    )


def get_escalation(conn: sqlite3.Connection, escalation_id: str) -> Escalation | None:
    row = conn.execute(
        f"SELECT {_ESCALATION_COLUMNS} FROM escalations WHERE id = ?", (escalation_id,)
    ).fetchone()
    return None if row is None else Escalation.model_validate(dict(row))


def find_open_escalation(conn: sqlite3.Connection, call_id: str) -> Escalation | None:
    row = conn.execute(
        f"SELECT {_ESCALATION_COLUMNS} FROM escalations WHERE call_id = ? AND status = 'open'",
        (call_id,),
    ).fetchone()
    return None if row is None else Escalation.model_validate(dict(row))


# --- Idempotency -----------------------------------------------------------------


@dataclass(frozen=True)
class IdempotencyRecord:
    action_id: str
    operation: str
    request_hash: str
    result_id: str


def get_idempotency_record(conn: sqlite3.Connection, action_id: str) -> IdempotencyRecord | None:
    row = conn.execute(
        "SELECT action_id, operation, request_hash, result_id "
        "FROM idempotency_keys WHERE action_id = ?",
        (action_id,),
    ).fetchone()
    return None if row is None else IdempotencyRecord(**dict(row))


def insert_idempotency_record(
    conn: sqlite3.Connection, record: IdempotencyRecord, now: datetime
) -> None:
    conn.execute(
        "INSERT INTO idempotency_keys (action_id, operation, request_hash, result_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            record.action_id,
            record.operation,
            record.request_hash,
            record.result_id,
            to_db_time(now),
        ),
    )
