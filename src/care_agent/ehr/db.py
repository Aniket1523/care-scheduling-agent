"""SQLite connection and schema for the mock EHR.

The schema enforces the invariants that must hold no matter which code writes
to it: foreign keys, allowed statuses, at most one booked appointment per slot,
and cancelled_at present exactly when an appointment is cancelled.

All timestamps are stored as UTC ISO-8601 strings with second precision, so
string comparison and ORDER BY match chronological order.

The audit log table is added with the feature that uses it (later milestone).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id          TEXT PRIMARY KEY,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    dob         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patient_phones (
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    phone       TEXT NOT NULL,
    PRIMARY KEY (patient_id, phone)
);
CREATE INDEX IF NOT EXISTS ix_patient_phones_phone ON patient_phones(phone);

CREATE TABLE IF NOT EXISTS providers (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    duration_min  INTEGER NOT NULL CHECK (duration_min > 0)
);

CREATE TABLE IF NOT EXISTS slots (
    id           TEXT PRIMARY KEY,
    provider_id  TEXT NOT NULL REFERENCES providers(id),
    start_at     TEXT NOT NULL,
    end_at       TEXT NOT NULL,
    CHECK (end_at > start_at)
);

CREATE TABLE IF NOT EXISTS appointments (
    id             TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients(id),
    provider_id    TEXT NOT NULL REFERENCES providers(id),
    service_id     TEXT NOT NULL REFERENCES services(id),
    slot_id        TEXT NOT NULL REFERENCES slots(id),
    start_at       TEXT NOT NULL,
    end_at         TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('booked', 'cancelled')),
    version        INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    cancelled_at   TEXT,
    cancel_reason  TEXT,
    CHECK (end_at > start_at),
    CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_appointments_patient ON appointments(patient_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_one_booking_per_slot
    ON appointments(slot_id) WHERE status = 'booked';

CREATE TABLE IF NOT EXISTS escalations (
    id          TEXT PRIMARY KEY,
    call_id     TEXT NOT NULL,
    patient_id  TEXT REFERENCES patients(id),
    reason      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_one_open_escalation_per_call
    ON escalations(call_id) WHERE status = 'open';

-- One row per completed logical action. Written in the same transaction as the
-- record it created, so "record exists" and "action recorded" never disagree.
CREATE TABLE IF NOT EXISTS idempotency_keys (
    action_id     TEXT PRIMARY KEY,
    operation     TEXT NOT NULL,
    request_hash  TEXT NOT NULL,
    result_id     TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced and rows accessible by name."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema. Safe to call more than once."""
    conn.executescript(SCHEMA)
