"""Tools the model may call, and their Python implementations.

Security rules enforced here, in code (not in the prompt):

* The caller's phone comes from the session, never from model arguments.
* Identity requires first name, last name and date of birth (ADR-019).
* No tool accepts a patient ID: patient-scoped tools act on the verified
  patient held in ``ConversationState``.
* Cancel and reschedule check that the appointment belongs to that patient.

Success verification: every write is followed by a fresh read of the EHR. An
outcome is recorded as ``verified`` in the ledger only if that read shows the
expected state. A timeout or error is retried with the same action ID (so it
cannot duplicate), and if retries run out the backend state is read to
reconcile what actually happened before anything is reported.
"""

from __future__ import annotations

import inspect
import re
import sqlite3
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from care_agent.agent import debug
from care_agent.agent.state import ConversationState, LedgerEntry, Operation, OutcomeStatus
from care_agent.ehr import repository as repo
from care_agent.ehr import service
from care_agent.ehr.faults import FaultPlan
from care_agent.ehr.models import Appointment
from care_agent.ehr.service import EHRError, EHRTimeout, ErrorCode
from care_agent.ids import new_id

MAX_WRITE_ATTEMPTS = 3

# Errors after which the write may or may not have happened.
_UNCERTAIN = (ErrorCode.INTERNAL_ERROR, ErrorCode.STALE_VERSION)

_DATE = {"type": "string", "description": "Date as YYYY-MM-DD."}

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "verify_identity",
        "description": (
            "Verify the caller as a patient using first name, last name and date of birth. "
            "Required before any appointment tool. The caller's phone number is used only "
            "as a hint."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "date_of_birth": _DATE,
            },
            "required": ["first_name", "last_name", "date_of_birth"],
        },
    },
    {
        "name": "register_patient",
        "description": (
            "Register a new patient. Only allowed after verify_identity returned NOT_FOUND "
            "for exactly the same details and the caller confirms they are new."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "first_name": {"type": "string"},
                "last_name": {"type": "string"},
                "date_of_birth": _DATE,
            },
            "required": ["first_name", "last_name", "date_of_birth"],
        },
    },
    {
        "name": "list_services",
        "description": "List the services the clinic offers, with their service IDs.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "find_slots",
        "description": "Find free appointment slots, earliest first.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {**_DATE, "description": "Optional day to search, YYYY-MM-DD."},
            },
        },
    },
    {
        "name": "list_my_appointments",
        "description": "List the verified patient's appointments with their appointment IDs.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "book_appointment",
        "description": "Book a free slot for the verified patient.",
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "From list_services (svc_...)."},
                "slot_id": {"type": "string", "description": "From find_slots (slot_...)."},
            },
            "required": ["service_id", "slot_id"],
        },
    },
    {
        "name": "cancel_appointment",
        "description": "Cancel one of the verified patient's appointments.",
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "From list_my_appointments (apt_...). Not a service ID.",
                },
                "reason": {"type": "string"},
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": "Move one of the verified patient's appointments to a free slot.",
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "From list_my_appointments (apt_...). Not a service ID.",
                },
                "new_slot_id": {"type": "string", "description": "From find_slots (slot_...)."},
            },
            "required": ["appointment_id", "new_slot_id"],
        },
    },
    {
        "name": "escalate_to_staff",
        "description": "Ask clinic staff to call the patient back about this call.",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    {
        "name": "reply_to_patient",
        "description": (
            "Send your reply to the patient. List in confirmed_action_ids only action IDs "
            "whose tool result had verified=true. Anything else is rejected."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "confirmed_action_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["message"],
        },
    },
]


# --- Result envelope (ToolResult) --------------------------------------------------


# ``action_id`` and ``verified`` appear only on results of writes (register, book,
# cancel, reschedule, escalate): ``verified`` is True only when a fresh EHR read
# confirmed the change. Reads and identity checks never carry them, so a
# successful lookup is not mistaken for an unverified one.


def ok(data: Any = None, *, action_id: str | None = None, verified: bool = False) -> dict:
    result: dict[str, Any] = {"status": "ok", "data": data}
    if action_id is not None:
        result["action_id"] = action_id
        result["verified"] = verified
    return result


def failed(code: str, message: str, *, action_id: str | None = None, guidance: str = "") -> dict:
    result: dict[str, Any] = {
        "status": "failed",
        "error": {"code": str(code), "message": message},
    }
    if action_id is not None:
        result["action_id"] = action_id
        result["verified"] = False
    if guidance:
        result["guidance"] = guidance
    return result


_TELL_THE_TRUTH = "Tell the patient it did not go through. Do not say it succeeded."


class ToolRunner:
    def __init__(
        self,
        conn: sqlite3.Connection,
        state: ConversationState,
        clock: Callable[[], datetime],
        faults: FaultPlan | None = None,
    ) -> None:
        self.conn = conn
        self.state = state
        self.clock = clock
        self.faults = faults
        # Action IDs written during the current turn (used for fallback replies).
        self.turn_actions: list[str] = []
        # Evaluation trace only (tool_attempt, reconcile_read, fault_injected events).
        # Never part of a tool result: the model does not see retries or faults.
        self.attempt_log: list[dict[str, Any]] = []
        self._faults_logged = 0
        self._handlers: dict[str, Callable[..., dict]] = {
            "verify_identity": self.verify_identity,
            "register_patient": self.register_patient,
            "list_services": self.list_services,
            "find_slots": self.find_slots,
            "list_my_appointments": self.list_my_appointments,
            "book_appointment": self.book_appointment,
            "cancel_appointment": self.cancel_appointment,
            "reschedule_appointment": self.reschedule_appointment,
            "escalate_to_staff": self.escalate_to_staff,
        }

    def execute(self, name: str, args: dict[str, Any]) -> dict:
        debug.log("tool_runner.received", tool=name, args=args)
        try:
            result = self._dispatch(name, args)
        except Exception as exc:
            debug.log("tool_runner.exception", tool=name, error=f"{type(exc).__name__}: {exc}")
            raise
        debug.log("tool_runner.result", tool=name, result=result)
        return result

    def _dispatch(self, name: str, args: dict[str, Any]) -> dict:
        handler = self._handlers.get(name)
        if handler is None:
            return failed("UNKNOWN_TOOL", f"there is no tool named {name!r}")
        try:
            inspect.signature(handler).bind(**args)
        except TypeError:
            # Missing or unexpected arguments, e.g. a patient_id the model invented.
            return failed(
                ErrorCode.INVALID_ARGUMENT, f"invalid arguments for {name}; follow its schema"
            )
        try:
            return handler(**args)
        except EHRError as exc:
            debug.log("tool_runner.ehr_error", tool=name, code=str(exc.code), message=str(exc))
            return failed(exc.code, str(exc), guidance=_TELL_THE_TRUTH)

    # --- Identity ------------------------------------------------------------------

    def verify_identity(self, first_name: str, last_name: str, date_of_birth: str) -> dict:
        dob = _parse_date(date_of_birth)
        debug.log("verify_identity.parse_date", raw=date_of_birth, parsed=dob)
        if dob is None:
            return {**_unreadable_dob(), "identity_status": "not_checked"}
        result = service.resolve_identity(
            self.conn, self.state.caller_phone, first_name, last_name, dob
        )
        debug.log(
            "verify_identity.resolve_identity",
            caller_phone=self.state.caller_phone,
            first_name=first_name,
            last_name=last_name,
            dob=dob,
            status=result.status,
            method=result.method,
            candidate_count=result.candidate_count,
            patient_id=result.patient.id if result.patient else None,
        )
        if result.status == "matched" and result.patient is not None:
            self.state.verified_patient = result.patient
            self.state.unmatched_identity = None
            return ok({"identity_status": "verified", "first_name": result.patient.first_name})
        if result.status == "not_found":
            self.state.unmatched_identity = _identity_key(first_name, last_name, dob)
            return _identity_failed(
                "not_found",
                failed(
                    ErrorCode.NOT_FOUND,
                    "no patient matches these details",
                    guidance=(
                        "Ask the caller to check the spelling and date of birth. If they say they "
                        "are a new patient, register_patient with exactly these details."
                    ),
                ),
            )
        if result.status == "ambiguous":
            return _identity_failed(
                "ambiguous",
                failed(
                    "AMBIGUOUS",
                    "more than one patient matches these details",
                    guidance=(
                        "Do not guess. Offer to have staff call them back (escalate_to_staff)."
                    ),
                ),
            )
        return _identity_failed(
            "verification_required",
            failed(
                "VERIFICATION_REQUIRED", "first name, last name and date of birth are all required"
            ),
        )

    def register_patient(self, first_name: str, last_name: str, date_of_birth: str) -> dict:
        dob = _parse_date(date_of_birth)
        if dob is None:
            return _unreadable_dob()
        if self.state.unmatched_identity != _identity_key(first_name, last_name, dob):
            return failed(
                "VERIFICATION_REQUIRED",
                "call verify_identity with these exact details first; register only if it "
                "returns NOT_FOUND",
            )
        action_id = self._new_action()
        patient = service.create_patient(
            self.conn, first_name, last_name, dob, self.state.caller_phone, self.clock()
        )
        fresh = repo.get_patient(self.conn, patient.id)
        if fresh is None:
            self._record(action_id, "register_patient", "unknown")
            return failed("UNVERIFIED", "registration could not be confirmed", action_id=action_id)
        self.state.verified_patient = fresh
        self.state.unmatched_identity = None
        summary = f"Registered {fresh.first_name} {fresh.last_name} as a new patient."
        self._record(action_id, "register_patient", "verified", summary)
        return ok({"registered": summary}, action_id=action_id, verified=True)

    # --- Reads ---------------------------------------------------------------------

    def list_services(self) -> dict:
        return ok(
            [
                {"service_id": s.id, "name": s.name, "duration_min": s.duration_min}
                for s in repo.list_services(self.conn)
            ]
        )

    def find_slots(self, date: str | None = None) -> dict:
        on_date = None
        if date:
            on_date = _parse_date(date)
            if on_date is None:
                return failed(ErrorCode.INVALID_ARGUMENT, "date must be YYYY-MM-DD")
        slots = repo.list_open_slots(self.conn, after=self.clock(), on_date=on_date)
        return ok(
            [
                {
                    "slot_id": s.id,
                    "start": _format_time(s.start_at),
                    "provider": repo.get_provider_name(self.conn, s.provider_id),
                }
                for s in slots
            ]
        )

    def list_my_appointments(self) -> dict:
        patient = self.state.verified_patient
        if patient is None:
            return _verification_required()
        return ok(
            [self._describe(a) for a in repo.list_appointments_for_patient(self.conn, patient.id)]
        )

    # --- Writes --------------------------------------------------------------------

    def book_appointment(self, service_id: str, slot_id: str) -> dict:
        patient = self.state.verified_patient
        if patient is None:
            return _verification_required()
        action_id = self._new_action()
        error: EHRError | None = None
        for attempt_no in range(1, MAX_WRITE_ATTEMPTS + 1):
            try:
                service.book_appointment(
                    self.conn,
                    patient.id,
                    service_id,
                    slot_id,
                    action_id=action_id,
                    now=self.clock(),
                    faults=self.faults,
                )
                self._log_attempt("book_appointment", action_id, attempt_no, "ok")
                break
            except EHRTimeout:
                self._log_attempt("book_appointment", action_id, attempt_no, "timeout")
                continue  # same action_id: a retry can never book twice
            except EHRError as exc:
                self._log_attempt("book_appointment", action_id, attempt_no, str(exc.code))
                if exc.code in _UNCERTAIN:
                    continue
                error = exc
                break
        if error is not None:
            self._record(action_id, "book_appointment", "failed")
            return failed(error.code, str(error), action_id=action_id, guidance=_TELL_THE_TRUTH)

        # Verify against the EHR, whether or not the last call reported success.
        booked = [
            a
            for a in repo.list_appointments_for_patient(self.conn, patient.id)
            if a.slot_id == slot_id and a.status == "booked"
        ]
        self._log_read("book_appointment", action_id, "booked" if booked else "not booked")
        if not booked:
            self._record(action_id, "book_appointment", "failed")
            return failed(
                "NOT_BOOKED",
                "the EHR did not respond and shows no booking for this slot",
                action_id=action_id,
                guidance=_TELL_THE_TRUTH,
            )
        appointment = booked[0]
        summary = f"{self._describe(appointment)['summary']} is booked."
        self._record(action_id, "book_appointment", "verified", summary)
        return ok(self._describe(appointment), action_id=action_id, verified=True)

    def cancel_appointment(self, appointment_id: str, reason: str | None = None) -> dict:
        before = self._owned_appointment(appointment_id)
        if isinstance(before, dict):
            return before
        if before.status == "cancelled":
            return failed(
                ErrorCode.ALREADY_CANCELLED,
                "this appointment is already cancelled",
                guidance="Tell the patient it was already cancelled.",
            )
        action_id = self._new_action()

        def attempt() -> None:
            service.cancel_appointment(
                self.conn,
                before.id,
                expected_version=before.version,
                now=self.clock(),
                reason=reason,
                faults=self.faults,
            )

        def done(current: Appointment) -> bool:
            return current.status == "cancelled"

        return self._versioned_write(
            action_id, "cancel_appointment", before, attempt, done, "is cancelled."
        )

    def reschedule_appointment(self, appointment_id: str, new_slot_id: str) -> dict:
        before = self._owned_appointment(appointment_id)
        if isinstance(before, dict):
            return before
        action_id = self._new_action()

        def attempt() -> None:
            service.reschedule_appointment(
                self.conn,
                before.id,
                new_slot_id,
                expected_version=before.version,
                now=self.clock(),
                faults=self.faults,
            )

        def done(current: Appointment) -> bool:
            return current.status == "booked" and current.slot_id == new_slot_id

        return self._versioned_write(
            action_id, "reschedule_appointment", before, attempt, done, "is now booked."
        )

    def escalate_to_staff(self, reason: str) -> dict:
        action_id = self._new_action()
        patient = self.state.verified_patient
        error: EHRError | None = None
        for attempt_no in range(1, MAX_WRITE_ATTEMPTS + 1):
            try:
                service.create_escalation(
                    self.conn,
                    self.state.call_id,
                    reason,
                    action_id=action_id,
                    now=self.clock(),
                    patient_id=patient.id if patient else None,
                    faults=self.faults,
                )
                self._log_attempt("escalate_to_staff", action_id, attempt_no, "ok")
                break
            except EHRTimeout:
                self._log_attempt("escalate_to_staff", action_id, attempt_no, "timeout")
                continue
            except EHRError as exc:
                self._log_attempt("escalate_to_staff", action_id, attempt_no, str(exc.code))
                if exc.code in _UNCERTAIN:
                    continue
                error = exc
                break
        if error is not None:
            self._record(action_id, "create_escalation", "failed")
            return failed(error.code, str(error), action_id=action_id, guidance=_TELL_THE_TRUTH)

        escalation = repo.find_open_escalation(self.conn, self.state.call_id)
        self._log_read(
            "escalate_to_staff", action_id, "open" if escalation else "no open escalation"
        )
        if escalation is None:
            self._record(action_id, "create_escalation", "failed")
            return failed(
                "NOT_ESCALATED",
                "the EHR did not respond and shows no escalation for this call",
                action_id=action_id,
                guidance=_TELL_THE_TRUTH,
            )
        summary = "A member of staff has been asked to call you back."
        self._record(action_id, "create_escalation", "verified", summary)
        return ok({"escalation": "open"}, action_id=action_id, verified=True)

    # --- Helpers -------------------------------------------------------------------

    def _versioned_write(
        self,
        action_id: str,
        operation: Operation,
        before: Appointment,
        attempt: Callable[[], None],
        done: Callable[[Appointment], bool],
        verified_suffix: str,
    ) -> dict:
        """Run a version-checked write, retrying only while the appointment is unchanged.

        After any failure the appointment is read again: if it already shows the
        intended change, the write happened (e.g. timeout after commit); if it is
        unchanged, retrying is safe; if someone else changed it, stop.
        """
        for attempt_no in range(1, MAX_WRITE_ATTEMPTS + 1):
            try:
                attempt()
                self._log_attempt(operation, action_id, attempt_no, "ok")
                break
            except (EHRTimeout, EHRError) as exc:
                outcome = "timeout" if isinstance(exc, EHRTimeout) else str(exc.code)
                self._log_attempt(operation, action_id, attempt_no, outcome)
                if isinstance(exc, EHRError) and exc.code not in _UNCERTAIN:
                    self._record(action_id, operation, "failed")
                    return failed(exc.code, str(exc), action_id=action_id, guidance=_TELL_THE_TRUTH)
                current = repo.get_appointment(self.conn, before.id)
                self._log_read(operation, action_id, _appointment_state(current))
                if current is not None and done(current):
                    break
                if current is None or current.version != before.version:
                    self._record(action_id, operation, "failed")
                    return failed(
                        ErrorCode.STALE_VERSION,
                        "the appointment was changed elsewhere during this request",
                        action_id=action_id,
                        guidance="Call list_my_appointments and tell the patient what it shows.",
                    )

        current = repo.get_appointment(self.conn, before.id)
        self._log_read(operation, action_id, _appointment_state(current))
        if current is None or not done(current):
            self._record(action_id, operation, "failed")
            return failed(
                "NOT_CONFIRMED",
                "the EHR does not show this change",
                action_id=action_id,
                guidance=_TELL_THE_TRUTH,
            )
        description = self._describe(current)
        self._record(
            action_id, operation, "verified", f"{description['summary']} {verified_suffix}"
        )
        return ok(description, action_id=action_id, verified=True)

    def _log_attempt(self, tool: str, action_id: str, attempt: int, outcome: str) -> None:
        """Record one internal write attempt, preceded by any fault it triggered."""
        fired = self.faults.fired if self.faults else []
        for operation, mode in fired[self._faults_logged :]:
            self.attempt_log.append(
                {"event": "fault_injected", "operation": operation, "mode": str(mode)}
            )
        self._faults_logged = len(fired)
        self.attempt_log.append(
            {
                "event": "tool_attempt",
                "tool": tool,
                "action_id": action_id,
                "attempt": attempt,
                "outcome": outcome,
            }
        )

    def _log_read(self, tool: str, action_id: str, found: str) -> None:
        """Record a read of the EHR made to confirm or reconcile a write."""
        self.attempt_log.append(
            {"event": "reconcile_read", "tool": tool, "action_id": action_id, "found": found}
        )

    def _owned_appointment(self, appointment_id: str) -> Appointment | dict:
        """Fresh read of an appointment that belongs to the verified patient."""
        patient = self.state.verified_patient
        if patient is None:
            return _verification_required()
        try:
            appointment_id = service.check_id("appointment_id", appointment_id)
        except EHRError as exc:
            return failed(exc.code, str(exc), guidance="Use an apt_ ID from list_my_appointments.")
        appointment = repo.get_appointment(self.conn, appointment_id)
        if appointment is None or appointment.patient_id != patient.id:
            # Same answer whether it does not exist or belongs to someone else.
            return failed(
                ErrorCode.NOT_FOUND,
                f"the patient has no appointment {appointment_id}",
                guidance="Call list_my_appointments to get the patient's appointment IDs.",
            )
        return appointment

    def _describe(self, appointment: Appointment) -> dict:
        service_row = repo.get_service(self.conn, appointment.service_id)
        provider = repo.get_provider_name(self.conn, appointment.provider_id)
        name = service_row.name if service_row else appointment.service_id
        when = _format_time(appointment.start_at)
        return {
            "appointment_id": appointment.id,
            "service": name,
            "provider": provider,
            "start": when,
            "status": appointment.status,
            "summary": f"{name} with {provider} on {when} (ref {appointment.id})",
        }

    def _new_action(self) -> str:
        action_id = new_id("act")
        self.turn_actions.append(action_id)
        return action_id

    def _record(
        self,
        action_id: str,
        operation: Operation,
        status: OutcomeStatus,
        summary: str | None = None,
    ) -> None:
        self.state.ledger.record(LedgerEntry(action_id, operation, status, summary))


def _identity_failed(identity_status: str, result: dict) -> dict:
    return {**result, "identity_status": identity_status}


def _unreadable_dob() -> dict:
    return failed(
        ErrorCode.INVALID_ARGUMENT,
        "date_of_birth could not be read as an unambiguous date",
        guidance=(
            "This is not a failed identity check. Confirm the date of birth with the caller "
            "(day, month name and year) and call again with date_of_birth as YYYY-MM-DD."
        ),
    )


def _appointment_state(appointment: Appointment | None) -> str:
    if appointment is None:
        return "missing"
    return f"{appointment.status} in {appointment.slot_id} (version {appointment.version})"


def _verification_required() -> dict:
    return failed(
        "VERIFICATION_REQUIRED",
        "the caller's identity is not verified",
        guidance="Ask for first name, last name and date of birth, then call verify_identity.",
    )


_ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[T ].*)?")
_ORDINAL_SUFFIX = re.compile(r"(?<=\d)(?:st|nd|rd|th)\b", re.IGNORECASE)
_WORD_MONTH_FORMATS = ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y")


def _parse_date(value: str) -> date | None:
    """Parse a date the model passed, accepting only unambiguous forms.

    Accepted: ISO ``1985-03-14`` (a trailing time part is ignored) and dates
    with the month as a word: ``14 March 1985``, ``March 14th, 1985``,
    ``14 Mar 1985``. All-numeric forms such as ``03/04/1985`` are rejected:
    day-first and month-first readings differ, and identity must not guess.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    iso = _ISO_DATE.fullmatch(text)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            return None
    text = " ".join(_ORDINAL_SUFFIX.sub("", text).replace(",", " ").split())
    for fmt in _WORD_MONTH_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _identity_key(first_name: str, last_name: str, dob: date) -> tuple[str, str, date]:
    return (first_name.strip().casefold(), last_name.strip().casefold(), dob)


def _format_time(value: datetime) -> str:
    return value.strftime("%a %d %b %Y %H:%M")


def new_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"
