"""Persistence functions for patients and appointments.

These functions store and load already-validated models. They contain no
scheduling rules (availability, booking, cancellation); those live in the EHR
service (M1b). Constraint violations surface as ``sqlite3.IntegrityError``.
Lookups of a missing record return ``None`` (or an empty list).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from care_agent.ehr.models import Appointment, Patient

_APPOINTMENT_COLUMNS = (
    "id, patient_id, provider_id, service_id, slot_id, start_at, end_at, status, version, "
    "created_at, updated_at, cancelled_at, cancel_reason"
)


def to_db_time(value: datetime) -> str:
    """Store an aware datetime as a UTC ISO-8601 string with second precision."""
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _optional_time(value: datetime | None) -> str | None:
    return None if value is None else to_db_time(value)


def insert_patient(conn: sqlite3.Connection, patient: Patient) -> None:
    """Insert a patient and their phone numbers in one transaction."""
    with conn:
        conn.execute(
            "INSERT INTO patients (id, first_name, last_name, dob, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
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


def insert_appointment(conn: sqlite3.Connection, appointment: Appointment) -> None:
    with conn:
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
