"""Domain models for the mock EHR.

Models validate data before it reaches the database. Timestamps must be
timezone-aware; the repository stores them in UTC.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from care_agent.ids import (
    AppointmentId,
    EscalationId,
    PatientId,
    ProviderId,
    ServiceId,
    SlotId,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Digits with an optional leading "+", 7-15 digits (E.164 length range).
Phone = Annotated[str, StringConstraints(pattern=r"^\+?[0-9]{7,15}$")]

AppointmentStatus = Literal["booked", "cancelled"]


class Service(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ServiceId
    name: Name
    duration_min: int = Field(gt=0)


class Slot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: SlotId
    provider_id: ProviderId
    start_at: AwareDatetime
    end_at: AwareDatetime


class Patient(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: PatientId
    first_name: Name
    last_name: Name
    dob: date
    phones: tuple[Phone, ...] = ()
    created_at: AwareDatetime


class Appointment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: AppointmentId
    patient_id: PatientId
    provider_id: ProviderId
    service_id: ServiceId
    slot_id: SlotId
    start_at: AwareDatetime
    end_at: AwareDatetime
    status: AppointmentStatus
    version: int = Field(default=1, ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    cancelled_at: AwareDatetime | None = None
    cancel_reason: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> Appointment:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if (self.status == "cancelled") != (self.cancelled_at is not None):
            raise ValueError("cancelled_at must be set if and only if status is 'cancelled'")
        return self


class Escalation(BaseModel):
    """A request for clinic staff to follow up on a call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: EscalationId
    call_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    patient_id: PatientId | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    status: Literal["open", "closed"] = "open"
    created_at: AwareDatetime
