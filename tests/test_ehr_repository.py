"""M1a: mock EHR database foundation — schema, models and repository."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from care_agent.ehr.db import connect, init_db
from care_agent.ehr.models import Appointment, Patient
from care_agent.ehr.repository import (
    get_appointment,
    get_patient,
    insert_appointment,
    insert_patient,
    list_appointments_for_patient,
)
from care_agent.ids import new_id

# Fixed clock value: tests never depend on the real time.
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)

PROVIDER_ID = "prv_drlee"
SERVICE_ID = "svc_cleaning"
SLOT_1 = ("slot_tue1000", "2026-11-17T10:00:00+00:00", "2026-11-17T10:30:00+00:00")
SLOT_2 = ("slot_wed0900", "2026-11-18T09:00:00+00:00", "2026-11-18T09:30:00+00:00")


@pytest.fixture
def conn(tmp_path):
    """A fresh, initialised database file in pytest's temp dir, with reference data.

    Providers, services and slots are inserted with plain SQL: they are fixed
    reference data, and their repository functions arrive with booking (M1b).
    """
    connection = connect(tmp_path / "ehr.sqlite3")
    init_db(connection)
    with connection:
        connection.execute("INSERT INTO providers VALUES (?, ?)", (PROVIDER_ID, "Dr Lee"))
        connection.execute("INSERT INTO services VALUES (?, ?, ?)", (SERVICE_ID, "Cleaning", 30))
        connection.executemany(
            "INSERT INTO slots VALUES (?, ?, ?, ?)",
            [(slot_id, PROVIDER_ID, start, end) for slot_id, start, end in (SLOT_1, SLOT_2)],
        )
    yield connection
    connection.close()


def make_patient(**overrides) -> Patient:
    fields = {
        "id": new_id("pat"),
        "first_name": "Maria",
        "last_name": "Garcia",
        "dob": date(1985, 3, 14),
        "phones": ("+15550100001",),
        "created_at": NOW,
    }
    return Patient(**(fields | overrides))


def make_appointment(patient_id: str, slot=SLOT_1, **overrides) -> Appointment:
    slot_id, start, end = slot
    fields = {
        "id": new_id("apt"),
        "patient_id": patient_id,
        "provider_id": PROVIDER_ID,
        "service_id": SERVICE_ID,
        "slot_id": slot_id,
        "start_at": start,
        "end_at": end,
        "status": "booked",
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Appointment(**(fields | overrides))


# --- Typed IDs ---------------------------------------------------------------


def test_new_id_has_prefix_and_is_unique():
    first, second = new_id("apt"), new_id("apt")
    assert first.startswith("apt_")
    assert first != second


def test_new_id_rejects_unknown_prefix():
    with pytest.raises(ValueError):
        new_id("xyz")


# --- Database initialisation ---------------------------------------------------


def test_init_db_creates_tables_and_enforces_foreign_keys(tmp_path):
    conn = connect(tmp_path / "fresh.sqlite3")
    try:
        init_db(conn)
        init_db(conn)  # idempotent: a second call must not fail
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"patients", "patient_phones", "providers", "services", "slots"} <= tables
        assert "appointments" in tables
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


# --- Patients ------------------------------------------------------------------


def test_patient_round_trip(conn):
    patient = make_patient(phones=("+15550100001", "+15550100099"))
    insert_patient(conn, patient)
    assert get_patient(conn, patient.id) == patient


def test_get_missing_patient_returns_none(conn):
    assert get_patient(conn, "pat_doesnotexist") is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "svc_cleaning"},  # wrong prefix
        {"first_name": "   "},  # blank name
        {"phones": ("not-a-phone",)},
        {"created_at": datetime(2026, 11, 12, 9, 0)},  # naive timestamp
    ],
)
def test_invalid_patient_is_rejected_before_storage(overrides):
    with pytest.raises(ValidationError):
        make_patient(**overrides)


def test_duplicate_patient_id_is_rejected(conn):
    patient = make_patient()
    insert_patient(conn, patient)
    with pytest.raises(sqlite3.IntegrityError):
        insert_patient(conn, make_patient(id=patient.id, phones=("+15550100777",)))
    assert get_patient(conn, patient.id) == patient  # original untouched


def test_failed_patient_insert_is_rolled_back(conn):
    # The patient row is written first; the repeated phone then violates the
    # patient_phones primary key. The whole insert must be undone.
    patient = make_patient(phones=("+15550100001", "+15550100001"))
    with pytest.raises(sqlite3.IntegrityError):
        insert_patient(conn, patient)
    assert get_patient(conn, patient.id) is None


# --- Appointments --------------------------------------------------------------


def test_appointment_round_trip(conn):
    patient = make_patient()
    insert_patient(conn, patient)
    appointment = make_appointment(patient.id)
    insert_appointment(conn, appointment)
    assert get_appointment(conn, appointment.id) == appointment


def test_get_missing_appointment_returns_none(conn):
    assert get_appointment(conn, "apt_doesnotexist") is None


def test_timestamps_are_stored_in_utc(conn):
    patient = make_patient()
    insert_patient(conn, patient)
    ist = timezone(timedelta(hours=5, minutes=30))
    created = datetime(2026, 11, 12, 14, 30, tzinfo=ist)  # 09:00 UTC
    appointment = make_appointment(patient.id, created_at=created, updated_at=created)
    insert_appointment(conn, appointment)

    raw = conn.execute(
        "SELECT created_at FROM appointments WHERE id = ?", (appointment.id,)
    ).fetchone()
    assert raw["created_at"] == "2026-11-12T09:00:00+00:00"
    assert get_appointment(conn, appointment.id).created_at == created  # same instant


def test_appointment_for_unknown_patient_is_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_appointment(conn, make_appointment("pat_doesnotexist"))


def test_service_id_in_appointment_id_field_is_rejected():
    # F4: a service ID where the appointment ID belongs.
    with pytest.raises(ValidationError):
        make_appointment("pat_maria", id=SERVICE_ID)


@pytest.mark.parametrize(
    "overrides",
    [
        {"end_at": SLOT_1[1]},  # ends when it starts
        {"status": "cancelled"},  # cancelled without cancelled_at
        {"cancelled_at": NOW},  # booked but has cancelled_at
        {"status": "no_show"},  # unknown status
        {"version": 0},
    ],
)
def test_inconsistent_appointment_is_rejected(overrides):
    with pytest.raises(ValidationError):
        make_appointment("pat_maria", **overrides)


def test_only_one_booked_appointment_per_slot(conn):
    first, second = make_patient(), make_patient(first_name="Ana")
    insert_patient(conn, first)
    insert_patient(conn, second)
    insert_appointment(conn, make_appointment(first.id, status="cancelled", cancelled_at=NOW))
    insert_appointment(conn, make_appointment(first.id))  # cancelled one does not block
    with pytest.raises(sqlite3.IntegrityError):
        insert_appointment(conn, make_appointment(second.id))


# --- Patient-appointment relationship ------------------------------------------


def test_list_appointments_returns_only_that_patients_in_start_order(conn):
    maria, ana = make_patient(), make_patient(first_name="Ana")
    insert_patient(conn, maria)
    insert_patient(conn, ana)
    later = make_appointment(maria.id, slot=SLOT_2)
    earlier = make_appointment(maria.id, slot=SLOT_1, status="cancelled", cancelled_at=NOW)
    other = make_appointment(ana.id, slot=SLOT_1)
    for appointment in (later, earlier, other):
        insert_appointment(conn, appointment)

    assert list_appointments_for_patient(conn, maria.id) == [earlier, later]
    assert list_appointments_for_patient(conn, ana.id) == [other]


def test_list_appointments_for_patient_without_any_is_empty(conn):
    patient = make_patient()
    insert_patient(conn, patient)
    assert list_appointments_for_patient(conn, patient.id) == []
    assert list_appointments_for_patient(conn, "pat_doesnotexist") == []
