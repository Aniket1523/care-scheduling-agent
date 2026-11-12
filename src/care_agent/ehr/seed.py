"""Minimal deterministic demo data for the interactive agent.

Given the same ``now``, ``seed_demo_data`` always produces the same rows:
two providers, two services, four slots a day on the next five weekdays, and
two demo patients who share a family phone situation (F3):

* Maria Garcia, DOB 1985-03-14, phone +15550100001, with one booked check-up.
* Luis Garcia, DOB 1983-07-02, phone +15550100002 (Maria's husband).

Times are in UTC; the demo clinic keeps UTC hours.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, time, timedelta

from care_agent.ehr import repository as repo
from care_agent.ehr.models import Appointment, Patient

PROVIDERS = (("prv_lee", "Dr Lee"), ("prv_kim", "Dr Kim"))
SERVICES = (("svc_cleaning", "Cleaning", 30), ("svc_checkup", "Check-up", 30))
SLOT_TIMES = (time(9, 0), time(10, 0), time(11, 0), time(14, 0))
SLOT_DAYS = 5

MARIA = {
    "id": "pat_maria",
    "first_name": "Maria",
    "last_name": "Garcia",
    "dob": date(1985, 3, 14),
    "phones": ("+15550100001",),
}
LUIS = {
    "id": "pat_luis",
    "first_name": "Luis",
    "last_name": "Garcia",
    "dob": date(1983, 7, 2),
    "phones": ("+15550100002",),
}


def demo_slots(now: datetime) -> list[tuple[str, str, datetime, datetime]]:
    """(slot_id, provider_id, start, end) for the next SLOT_DAYS weekdays after ``now``."""
    slots = []
    day = now.astimezone(UTC).date()
    while len(slots) < SLOT_DAYS * len(SLOT_TIMES):
        day += timedelta(days=1)
        if day.weekday() >= 5:  # skip Saturday and Sunday
            continue
        for index, slot_time in enumerate(SLOT_TIMES):
            provider_id = PROVIDERS[index % 2][0]
            start = datetime.combine(day, slot_time, tzinfo=UTC)
            slot_id = f"slot_{day:%Y%m%d}{slot_time:%H%M}{provider_id[4:]}"
            slots.append((slot_id, provider_id, start, start + timedelta(minutes=30)))
    return slots


def seed_demo_data(conn: sqlite3.Connection, now: datetime) -> None:
    slots = demo_slots(now)
    with conn:
        conn.executemany("INSERT INTO providers (id, name) VALUES (?, ?)", PROVIDERS)
        conn.executemany("INSERT INTO services (id, name, duration_min) VALUES (?, ?, ?)", SERVICES)
        conn.executemany(
            "INSERT INTO slots (id, provider_id, start_at, end_at) VALUES (?, ?, ?, ?)",
            [(sid, pid, repo.to_db_time(s), repo.to_db_time(e)) for sid, pid, s, e in slots],
        )
        for fields in (MARIA, LUIS):
            repo.insert_patient(conn, Patient(**fields, created_at=now))

        # Maria already has a check-up in the second slot of the second day.
        slot_id, provider_id, start, end = slots[len(SLOT_TIMES) + 1]
        repo.insert_appointment(
            conn,
            Appointment(
                id="apt_mariacheckup",
                patient_id=MARIA["id"],
                provider_id=provider_id,
                service_id="svc_checkup",
                slot_id=slot_id,
                start_at=start,
                end_at=end,
                status="booked",
                created_at=now,
                updated_at=now,
            ),
        )
