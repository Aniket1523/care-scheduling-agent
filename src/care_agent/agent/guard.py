"""Claim guard (ADR-011, IMP-002): nothing reaches the patient as done unless the EHR shows it.

The model replies through ``reply_to_patient(message, confirmed_action_ids)``.

1. Primary, structural check: every confirmed action ID must be ``verified``
   in this call's ``OutcomeLedger``. The confirmation details the patient
   hears are appended from the ledger, i.e. from data read back from the EHR,
   so the model cannot state a date or time it was not given.
2. Backstop for free text, with two kinds of evidence kept apart:

   * an *action claim* ("I've cancelled it", "I booked you in") says the agent
     did something. Only a verified action of that type in this call supports it.
   * a *state claim* ("it has already been cancelled", "you're booked") says how
     things are. A verified action supports it, and so does a fresh EHR read
     showing an appointment cancelled, whoever cancelled it. Only cancelled
     observations count: cancelled is final, while a "booked" read can go stale.

   Free text names no records, so the evidence must point to exactly one: one
   appointment for that operation in this call (or the call's escalation).
   Otherwise the model must list the action_id in ``confirmed_action_ids``.

The wording patterns are deliberately narrow and only decide which kind of
evidence a sentence needs; the evidence itself comes from the ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from care_agent.agent.state import OutcomeLedger

_FLAGS = re.IGNORECASE

# First person: "I've cancelled", "I have booked", "we cancelled", "I've gone ahead and booked".
# Negations ("I haven't cancelled", "I have not booked") and other tenses ("I'll cancel",
# "I tried to cancel") do not match.
_FIRST_PERSON = (
    r"(?<![\w'])(?:i|we)(?:'ve|\s+have|'d|\s+had)?\s+"
    r"(?:(?:just|now|already|successfully|also|gone\s+ahead\s+and)\s+)*"
)
ACTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "book_appointment": re.compile(_FIRST_PERSON + r"(?:booked|scheduled)\b", _FLAGS),
    "cancel_appointment": re.compile(_FIRST_PERSON + r"cancell?ed\b", _FLAGS),
    "reschedule_appointment": re.compile(_FIRST_PERSON + r"(?:rescheduled|moved)\b", _FLAGS),
    "create_escalation": re.compile(
        _FIRST_PERSON + r"(?:escalated|notified|flagged|forwarded|highlighted"
        r"|passed\s+(?:this|it|that|your\s+request)\s+on"
        r"|let\s+(?:the|our)\s+(?:clinic\s+)?(?:team|staff)\s+know"
        r"|asked\s+(?:a\s+member\s+of\s+(?:the\s+)?(?:clinic\s+)?staff|(?:the|our)\s+"
        r"(?:clinic\s+)?(?:team|staff)|staff))\b",
        _FLAGS,
    ),
}

# Passive / state: "is booked", "has already been cancelled", "you're all set".
# Negated forms ("has not been cancelled", "isn't booked") do not match.
_STATE_AUX = (
    r"(?<!not )(?<!n't )(?<!never )\b(?:is|are|'re|was|were|been|has)\s+"
    r"(?:(?:now|all|already|just|successfully)\s+)*"
)
STATE_PATTERNS: dict[str, re.Pattern[str]] = {
    "book_appointment": re.compile(
        _STATE_AUX + r"(?:booked|scheduled)\b|\byou'?re all set\b", _FLAGS
    ),
    "cancel_appointment": re.compile(_STATE_AUX + r"cancell?ed\b", _FLAGS),
    "reschedule_appointment": re.compile(_STATE_AUX + r"(?:rescheduled|moved)\b", _FLAGS),
    "create_escalation": re.compile(
        _STATE_AUX + r"(?:escalated|notified|passed\s+(?:this|it|that)\s+on|asked\s+to\s+call)\b",
        _FLAGS,
    ),
}


def classify_claims(message: str) -> tuple[set[str], set[str]]:
    """(operations claimed as the agent's own actions, operations claimed as current state)."""
    actions = {op for op, pattern in ACTION_PATTERNS.items() if pattern.search(message)}
    states = {op for op, pattern in STATE_PATTERNS.items() if pattern.search(message)}
    return actions, states


def claimed_operations(message: str) -> set[str]:
    """Operation types the message reads as having completed, in either form."""
    actions, states = classify_claims(message)
    return actions | states


def action_evidence(ledger: OutcomeLedger, operation: str) -> set[str]:
    """Records that verified actions of this type in the call concern."""
    return {
        "call" if operation == "create_escalation" else (e.record_id or e.action_id)
        for e in ledger.verified()
        if e.operation == operation
    }


def state_evidence(ledger: OutcomeLedger, operation: str) -> set[str]:
    """Records whose state the call can vouch for: verified actions, plus (for
    cancellation only) appointments a fresh EHR read showed as cancelled."""
    records = action_evidence(ledger, operation)
    if operation == "cancel_appointment":
        records |= {aid for aid, status in ledger.observed.items() if status == "cancelled"}
    return records


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

    action_claims, state_claims = classify_claims(message)
    for op in sorted(action_claims - confirmed_ops):
        problems.extend(
            _evidence_problems(
                op,
                action_evidence(ledger, op),
                f"the message says you performed {op}, but this call has no verified {op} action "
                "(an appointment cancelled elsewhere is 'already cancelled', not cancelled by you)",
            )
        )
    for op in sorted(state_claims - confirmed_ops - action_claims):
        problems.extend(
            _evidence_problems(
                op,
                state_evidence(ledger, op),
                f"the message says {op} has happened, but no verified action or fresh EHR read "
                "in this call shows it",
            )
        )

    if problems:
        return GuardDecision(ok=False, text="", problems=tuple(problems))
    text = message.strip()
    if summaries:
        text += "\n" + "\n".join(f"Confirmed: {s}" for s in summaries)
    return GuardDecision(ok=True, text=text)


def _evidence_problems(operation: str, records: set[str], missing: str) -> list[str]:
    if not records:
        return [missing]
    if len(records) > 1:
        return [
            f"the message mentions {operation}, but more than one record could be meant; "
            "list the action_id in confirmed_action_ids"
        ]
    return []


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
