"""Persistence functions for the mock EHR.

These functions store and load data. They contain no scheduling rules
(availability, whether something may be cancelled); those live in
``care_agent.ehr.service``. Constraint violations surface as
``sqlite3.IntegrityError``. Lookups of a missing record return ``None`` (or an
empty list).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

from care_agent.ehr.models import Appointment, Patient, Service, Slot

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


def mark_cancelled(
    conn: sqlite3.Connection, appointment_id: str, reason: str | None, now: datetime
) -> bool:
    """Cancel a booked appointment. Returns False if it was not in 'booked' state."""
    with conn:
        cursor = conn.execute(
            "UPDATE appointments SET status = 'cancelled', cancelled_at = ?, cancel_reason = ?, "
            "updated_at = ?, version = version + 1 WHERE id = ? AND status = 'booked'",
            (to_db_time(now), reason, to_db_time(now), appointment_id),
        )
    return cursor.rowcount == 1


def move_to_slot(conn: sqlite3.Connection, appointment_id: str, slot: Slot, now: datetime) -> bool:
    """Move a booked appointment to another slot in a single UPDATE.

    One statement is atomic: either the appointment moves completely (slot,
    provider, times, version) or nothing changes. If the new slot is already
    booked, the one-booking-per-slot index raises IntegrityError and the
    appointment keeps its original slot. Returns False if it was not 'booked'.
    """
    with conn:
        cursor = conn.execute(
            "UPDATE appointments SET slot_id = ?, provider_id = ?, start_at = ?, end_at = ?, "
            "updated_at = ?, version = version + 1 WHERE id = ? AND status = 'booked'",
            (
                slot.id,
                slot.provider_id,
                to_db_time(slot.start_at),
                to_db_time(slot.end_at),
                to_db_time(now),
                appointment_id,
            ),
        )
    return cursor.rowcount == 1
