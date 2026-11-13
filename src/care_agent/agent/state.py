"""Per-call application state: who the caller is and what verifiably happened.

The model never holds authority here. The caller's phone comes from the
session, the verified patient is set only by the identity tool, and the
``OutcomeLedger`` records only what was confirmed by reading the EHR back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from care_agent.ehr.models import Patient

Operation = Literal[
    "register_patient",
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
    "create_escalation",
]
OutcomeStatus = Literal["verified", "failed", "unknown"]


@dataclass(frozen=True)
class LedgerEntry:
    action_id: str
    operation: Operation
    status: OutcomeStatus
    # Patient-facing description built from data read back from the EHR.
    # Set only for verified outcomes.
    summary: str | None = None
    # The record the action concerns (appointment or patient ID), when known.
    record_id: str | None = None


@dataclass
class OutcomeLedger:
    """Two kinds of evidence, kept apart (ADR-011, IMP-002):

    * ``entries``: actions this agent performed, keyed by action_id. Only a
      ``verified`` entry shows the agent did something.
    * ``observed``: appointment states seen in fresh EHR reads during the call,
      whoever caused them. An observation can show that an appointment *is*
      cancelled, never that the agent cancelled it.
    """

    entries: dict[str, LedgerEntry] = field(default_factory=dict)
    observed: dict[str, str] = field(default_factory=dict)  # appointment_id -> status

    def record(self, entry: LedgerEntry) -> LedgerEntry:
        self.entries[entry.action_id] = entry
        return entry

    def observe(self, appointment_id: str, status: str) -> None:
        self.observed[appointment_id] = status

    def get(self, action_id: str) -> LedgerEntry | None:
        return self.entries.get(action_id)

    def verified(self) -> list[LedgerEntry]:
        return [e for e in self.entries.values() if e.status == "verified"]


@dataclass
class ConversationState:
    call_id: str
    caller_phone: str
    verified_patient: Patient | None = None
    # Details of the last identity check that found no patient. Registration is
    # allowed only for exactly these details (see the register_patient tool).
    unmatched_identity: tuple[str, str, date] | None = None
    ledger: OutcomeLedger = field(default_factory=OutcomeLedger)
