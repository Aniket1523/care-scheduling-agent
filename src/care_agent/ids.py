"""Typed, prefixed identifiers (ADR-007).

Every ID carries a prefix naming its entity, e.g. ``apt_3f9c1a2b4d5e``. Pydantic
fields typed with the aliases below reject an ID with the wrong prefix, so a
service ID passed where an appointment ID belongs (F4) is a validation error
rather than a silent backend failure.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import StringConstraints

PatientId = Annotated[str, StringConstraints(pattern=r"^pat_[A-Za-z0-9]+$")]
ProviderId = Annotated[str, StringConstraints(pattern=r"^prv_[A-Za-z0-9]+$")]
ServiceId = Annotated[str, StringConstraints(pattern=r"^svc_[A-Za-z0-9]+$")]
SlotId = Annotated[str, StringConstraints(pattern=r"^slot_[A-Za-z0-9]+$")]
AppointmentId = Annotated[str, StringConstraints(pattern=r"^apt_[A-Za-z0-9]+$")]
EscalationId = Annotated[str, StringConstraints(pattern=r"^esc_[A-Za-z0-9]+$")]
ActionId = Annotated[str, StringConstraints(pattern=r"^act_[A-Za-z0-9]+$")]

PREFIXES = frozenset({"pat", "prv", "svc", "slot", "apt", "esc", "act"})


def new_id(prefix: str) -> str:
    """Return a new random ID such as ``pat_3f9c1a2b4d5e``."""
    if prefix not in PREFIXES:
        raise ValueError(f"unknown ID prefix: {prefix!r}")
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
