"""Shared test data for EHR tests: fixed clock, reference rows and model builders.

Imported as ``from ehr_data import ...`` (pytest puts the tests directory on
sys.path), which works under both ``pytest`` and ``python -m pytest``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

from care_agent.ehr.models import Appointment, Patient
from care_agent.ids import new_id

# Fixed clock value: tests never depend on the real time.
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)

PROVIDER_ID = "prv_drlee"
PROVIDER_2_ID = "prv_drkim"
SERVICE_ID = "svc_cleaning"
SLOT_1 = ("slot_tue1000", "2026-11-17T10:00:00+00:00", "2026-11-17T10:30:00+00:00")
SLOT_2 = ("slot_wed0900", "2026-11-18T09:00:00+00:00", "2026-11-18T09:30:00+00:00")
SLOT_3 = ("slot_thu1400", "2026-11-19T14:00:00+00:00", "2026-11-19T14:30:00+00:00")  # Dr Kim
SLOT_PAST = ("slot_mon0800", "2026-11-10T08:00:00+00:00", "2026-11-10T08:30:00+00:00")


def seed_reference_data(conn: sqlite3.Connection) -> None:
    """Providers, services and slots, inserted with plain SQL (fixed reference data)."""
    with conn:
        conn.executemany(
            "INSERT INTO providers VALUES (?, ?)",
            [(PROVIDER_ID, "Dr Lee"), (PROVIDER_2_ID, "Dr Kim")],
        )
        conn.execute("INSERT INTO services VALUES (?, ?, ?)", (SERVICE_ID, "Cleaning", 30))
        conn.executemany(
            "INSERT INTO slots VALUES (?, ?, ?, ?)",
            [
                (SLOT_1[0], PROVIDER_ID, SLOT_1[1], SLOT_1[2]),
                (SLOT_2[0], PROVIDER_ID, SLOT_2[1], SLOT_2[2]),
                (SLOT_3[0], PROVIDER_2_ID, SLOT_3[1], SLOT_3[2]),
                (SLOT_PAST[0], PROVIDER_ID, SLOT_PAST[1], SLOT_PAST[2]),
            ],
        )


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
