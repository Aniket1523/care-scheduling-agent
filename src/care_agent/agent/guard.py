"""Claim guard (ADR-011): nothing reaches the patient as done unless the EHR shows it.

The model replies through ``reply_to_patient(message, confirmed_action_ids)``.

1. Primary, structural check: every confirmed action ID must be ``verified``
   in this call's ``OutcomeLedger``. The confirmation details the patient
   hears are appended from the ledger, i.e. from data read back from the EHR,
   so the model cannot state a date or time it was not given.
2. Backstop: a small detector for success wording ("you're booked", "has been
   cancelled", ...). If the message claims an operation type that no confirmed,
   verified action covers, the reply is rejected. It is deliberately narrow; it
   is not the main defence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from care_agent.agent.state import OutcomeLedger

# "<auxiliary> <past participle>", e.g. "is booked", "have cancelled", "'ve escalated".
# Negated forms ("has not been cancelled", "hasn't been booked") are excluded.
_AUX = r"(?<!not )(?<!n't )(?<!never )\b(?:is|are|'re|was|been|have|has|'ve)\s+(?:now\s+|all\s+)?"
CLAIM_PATTERNS: dict[str, re.Pattern[str]] = {
    "book_appointment": re.compile(_AUX + r"(?:booked|scheduled)\b|\byou'?re all set\b", re.I),
    "cancel_appointment": re.compile(_AUX + r"cancell?ed\b", re.I),
    "reschedule_appointment": re.compile(_AUX + r"(?:rescheduled|moved)\b", re.I),
    "create_escalation": re.compile(
        _AUX + r"(?:escalated|passed (?:this|it|that) on|notified|let (?:the|our) team know)\b",
        re.I,
    ),
}


def claimed_operations(message: str) -> set[str]:
    """Operation types the message reads as having completed."""
    return {op for op, pattern in CLAIM_PATTERNS.items() if pattern.search(message)}


@dataclass(frozen=True)
class GuardDecision:
    ok: bool
    text: str  # what the patient will hear (only meaningful when ok)
    problems: tuple[str, ...] = ()


def check_reply(
    message: str, confirmed_action_ids: list[str], ledger: OutcomeLedger
) -> GuardDecision:
    problems = []
    confirmed_ops = set()
    summaries = []
    for action_id in confirmed_action_ids:
        entry = ledger.get(action_id)
        if entry is None or entry.status != "verified":
            problems.append(f"{action_id} is not a verified outcome in this call")
            continue
        confirmed_ops.add(entry.operation)
        if entry.summary:
            summaries.append(entry.summary)

    for op in sorted(claimed_operations(message) - confirmed_ops):
        problems.append(f"the message claims {op} succeeded, but no verified action confirms it")

    if problems:
        return GuardDecision(ok=False, text="", problems=tuple(problems))
    text = message.strip()
    if summaries:
        text += "\n" + "\n".join(f"Confirmed: {s}" for s in summaries)
    return GuardDecision(ok=True, text=text)


def fallback_reply(ledger: OutcomeLedger, action_ids: list[str]) -> str:
    """Deterministic, truthful reply built only from the ledger.

    Used when the model's reply was rejected twice or the model failed.
    ``action_ids`` are the actions attempted during the current turn.
    """
    lines = []
    for action_id in action_ids:
        entry = ledger.get(action_id)
        if entry is None:
            continue
        if entry.status == "verified" and entry.summary:
            lines.append(f"Confirmed: {entry.summary}")
        elif entry.status == "unknown":
            lines.append(f"I could not confirm whether the {_label(entry.operation)} went through.")
        elif entry.status == "failed":
            lines.append(f"The {_label(entry.operation)} did not go through.")
    lines.append(
        "I'm sorry, I'm having trouble completing this. "
        "Could you repeat that, or would you like a member of staff to call you back?"
    )
    return "\n".join(lines)


def _label(operation: str) -> str:
    return {
        "register_patient": "registration",
        "book_appointment": "booking",
        "cancel_appointment": "cancellation",
        "reschedule_appointment": "reschedule",
        "create_escalation": "request for a staff callback",
    }.get(operation, operation)
