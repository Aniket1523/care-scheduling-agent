"""Deterministic fault injection for the mock EHR (tests and evals only).

A ``FaultPlan`` holds, per write operation, a queue of faults consumed one per
call: ``FaultPlan({"book_appointment": [FaultMode.TIMEOUT_AFTER_COMMIT]})``
makes the first booking time out after it committed and lets later bookings
succeed. ``None`` in a queue means "no fault for this call", so
``[None, FaultMode.ERROR_AFTER_COMMIT]`` faults only the second call.

No randomness and no real waiting: a simulated timeout is raised immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Operations that write to the EHR and can therefore be faulted.
WRITE_OPERATIONS = frozenset(
    {"book_appointment", "cancel_appointment", "reschedule_appointment", "create_escalation"}
)


class FaultMode(StrEnum):
    # The write is rolled back; the caller sees a timeout. Nothing happened.
    TIMEOUT_BEFORE_COMMIT = "timeout_before_commit"
    # The write committed; the caller sees a timeout. It did happen.
    TIMEOUT_AFTER_COMMIT = "timeout_after_commit"
    # The write committed; the caller sees an error. It did happen.
    ERROR_AFTER_COMMIT = "error_after_commit"


@dataclass
class FaultPlan:
    queues: dict[str, list[FaultMode | None]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = set(self.queues) - WRITE_OPERATIONS
        if unknown:
            raise ValueError(f"unknown operations in fault plan: {sorted(unknown)}")

    def next_fault(self, operation: str) -> FaultMode | None:
        queue = self.queues.get(operation)
        return queue.pop(0) if queue else None
