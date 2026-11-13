"""M2: the scheduling agent, driven by a scripted model (no network, no API key)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_fakes import (
    ScriptedModel,
    call,
    last_results,
    reply,
    reply_claiming_last_action,
    reply_confirming_last,
    say,
)
from care_agent.agent.guard import check_reply, claimed_operations
from care_agent.agent.loop import MAX_MODEL_CALLS, Agent
from care_agent.agent.state import ConversationState, LedgerEntry, OutcomeLedger
from care_agent.agent.tools import ToolRunner
from care_agent.ehr import repository as repo
from care_agent.ehr import service
from care_agent.ehr.db import connect, init_db
from care_agent.ehr.faults import FaultMode, FaultPlan
from care_agent.ehr.seed import demo_slots, seed_demo_data

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)  # a Thursday
MARIA_PHONE, LUIS_PHONE, UNKNOWN_PHONE = "+15550100001", "+15550100002", "+15550109999"
MARIA = {"first_name": "Maria", "last_name": "Garcia", "date_of_birth": "1985-03-14"}
LUIS = {"first_name": "Luis", "last_name": "Garcia", "date_of_birth": "1983-07-02"}
MARIA_APT = "apt_mariacheckup"
FRI_0900 = "slot_202611130900lee"
TUE_0900 = "slot_202611170900lee"


@pytest.fixture
def ehr(tmp_path):
    conn = connect(tmp_path / "agent.sqlite3")
    init_db(conn)
    seed_demo_data(conn, NOW)
    yield conn
    conn.close()


def make_agent(conn, steps, phone=MARIA_PHONE, faults=None):
    state = ConversationState(call_id="call_test", caller_phone=phone)
    model = ScriptedModel(steps)
    agent = Agent(model, ToolRunner(conn, state, lambda: NOW, faults), state)
    return agent, model, state


def booked_count(conn) -> int:
    return conn.execute("SELECT count(*) FROM appointments WHERE status = 'booked'").fetchone()[0]


def result_of(model: ScriptedModel, step_index: int) -> dict:
    """The tool result the model saw at the start of a given generate() call."""
    return last_results(model.seen[step_index])[0]


# --- Conversation flow -----------------------------------------------------------


def test_multi_turn_conversation_verifies_identity_and_books(ehr):
    agent, model, state = make_agent(
        ehr,
        [
            reply("Happy to help. What is your full name and date of birth?"),
            call("verify_identity", **MARIA),
            reply("Thanks Maria. Friday 13 November at 09:00 with Dr Lee is free. Shall I book?"),
            call("book_appointment", service_id="svc_cleaning", slot_id=FRI_0900),
            reply_confirming_last("You're booked!"),
        ],
    )
    assert "full name" in agent.respond("Hi, I need a cleaning")
    assert "Shall I book" in agent.respond("Maria Garcia, 14 March 1985")
    final = agent.respond("Yes please")

    assert "You're booked!" in final
    assert "Confirmed: Cleaning with Dr Lee on Fri 13 Nov 2026 09:00" in final
    assert state.verified_patient is not None and state.verified_patient.id == "pat_maria"
    assert repo.slot_is_booked(ehr, FRI_0900)
    # The model saw the whole conversation on the last turn.
    assert any("cleaning" in (p.text or "") for c in model.seen[-1] for p in c.parts or [])
    model.assert_finished()


# --- Identity (F3) ---------------------------------------------------------------


def test_caller_phone_alone_does_not_verify_identity(ehr):
    agent, model, _ = make_agent(
        ehr,
        [
            call("book_appointment", service_id="svc_cleaning", slot_id=FRI_0900),
            reply("I need to confirm who you are first."),
        ],
    )
    agent.respond("Book me a cleaning on Friday at 9")
    assert result_of(model, 1)["error"]["code"] == "VERIFICATION_REQUIRED"
    assert not repo.slot_is_booked(ehr, FRI_0900)
    model.assert_finished()


def test_spouse_phone_with_correct_details_verifies_the_caller(ehr):
    agent, model, state = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("list_my_appointments"),
            reply("You have a check-up on Monday."),
        ],
        phone=LUIS_PHONE,
    )
    agent.respond("It's Maria Garcia, born 1985-03-14, calling from my husband's phone")
    assert state.verified_patient.id == "pat_maria"
    appointments = result_of(model, 2)["data"]
    assert [a["appointment_id"] for a in appointments] == [MARIA_APT]
    model.assert_finished()


def verify_via_dispatcher(conn, phone, date_of_birth, first_name="Maria", last_name="Garcia"):
    state = ConversationState(call_id="call_test", caller_phone=phone)
    result = ToolRunner(conn, state, lambda: NOW).execute(
        "verify_identity",
        {"first_name": first_name, "last_name": last_name, "date_of_birth": date_of_birth},
    )
    return result, state


@pytest.mark.parametrize(
    "date_of_birth",
    [
        "1985-03-14",
        "14 March 1985",  # the reported failure: caller said "Maria Garcia, 14 March 1985."
        "March 14, 1985",
        "14th March 1985",
        "14 Mar 1985",
        "1985-03-14T00:00:00Z",
    ],
)
def test_spouse_phone_verifies_maria_for_unambiguous_dob_formats(ehr, date_of_birth):
    # Regression: Maria calling from Luis's phone (F3, ADR-019) with a non-ISO DOB was
    # rejected at the tool boundary as INVALID_ARGUMENT, so she could not be verified.
    result, state = verify_via_dispatcher(ehr, LUIS_PHONE, date_of_birth)
    assert result["status"] == "ok", result
    assert state.verified_patient.id == "pat_maria"


@pytest.mark.parametrize("date_of_birth", ["03/14/1985", "14/03/1985", "1985-02-30", "soon"])
def test_ambiguous_or_invalid_dob_is_not_guessed(ehr, date_of_birth):
    result, state = verify_via_dispatcher(ehr, LUIS_PHONE, date_of_birth)
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert "Confirm the date of birth" in result["guidance"]
    assert state.verified_patient is None


def test_wrong_dob_in_words_is_still_not_found_and_creates_nothing(ehr):
    patients_before = ehr.execute("SELECT count(*) FROM patients").fetchone()[0]
    result, state = verify_via_dispatcher(ehr, LUIS_PHONE, "15 March 1985")
    assert result["error"]["code"] == "NOT_FOUND"
    assert state.verified_patient is None
    assert ehr.execute("SELECT count(*) FROM patients").fetchone()[0] == patients_before


def test_phone_owner_is_not_verified_without_matching_details(ehr):
    # Luis's phone with no usable details for Luis: nobody is verified.
    result, state = verify_via_dispatcher(ehr, LUIS_PHONE, "2 July 1983", first_name="Maria")
    assert result["error"]["code"] == "NOT_FOUND"
    assert state.verified_patient is None


def test_reported_conversation_through_the_agent_loop(ehr):
    # The exact failing conversation, with the DOB passed as the caller said it.
    agent, model, state = make_agent(
        ehr,
        [
            reply("Could you tell me your first name, last name and date of birth?"),
            call(
                "verify_identity",
                first_name="Maria",
                last_name="Garcia",
                date_of_birth="14 March 1985",
            ),
            reply("Thanks Maria, you're verified. Which day suits you?"),
        ],
        phone=LUIS_PHONE,
    )
    agent.respond("I'd like to book an appointment.")
    final = agent.respond("Maria Garcia, 14 March 1985.")
    assert result_of(model, 2)["status"] == "ok"
    assert state.verified_patient.id == "pat_maria"
    assert final == "Thanks Maria, you're verified. Which day suits you?"
    model.assert_finished()


def test_successful_identity_result_is_unambiguous(ehr):
    # Regression: the real Gemini run sent exactly these arguments from Luis's phone. The
    # EHR matched Maria, but the result also said "verified": false (meant for writes),
    # and Gemini told her no record was found.
    result, state = verify_via_dispatcher(ehr, LUIS_PHONE, "1985-03-14")
    assert result == {
        "status": "ok",
        "data": {"identity_status": "verified", "first_name": "Maria"},
    }
    assert "verified" not in result  # write-confirmation field is absent, not false
    assert state.verified_patient.id == "pat_maria"


def test_identity_result_seen_by_the_model_is_unambiguous(ehr):
    agent, model, state = make_agent(
        ehr,
        [
            call(
                "verify_identity",
                first_name="Maria",
                last_name="Garcia",
                date_of_birth="1985-03-14",
            ),
            reply("Thanks Maria, you're verified."),
        ],
        phone=LUIS_PHONE,
    )
    agent.respond("Maria Garcia, 14 March 1985.")
    sent_to_model = result_of(model, 1)
    assert sent_to_model["data"]["identity_status"] == "verified"
    assert "verified" not in sent_to_model
    assert state.verified_patient.id == "pat_maria"
    model.assert_finished()


def test_patient_scoped_tools_use_the_verified_patient(ehr):
    state = ConversationState(call_id="call_test", caller_phone=LUIS_PHONE)
    runner = ToolRunner(ehr, state, lambda: NOW)
    identity = runner.execute(
        "verify_identity",
        {"first_name": "Maria", "last_name": "Garcia", "date_of_birth": "1985-03-14"},
    )
    assert identity["data"]["identity_status"] == "verified"

    listed = runner.execute("list_my_appointments", {})
    assert [a["appointment_id"] for a in listed["data"]] == [MARIA_APT]

    booked = runner.execute("book_appointment", {"service_id": "svc_cleaning", "slot_id": FRI_0900})
    assert booked["verified"] is True and booked["action_id"].startswith("act_")
    appointment = repo.get_appointment(ehr, booked["data"]["appointment_id"])
    assert appointment.patient_id == "pat_maria"  # not Luis, whose phone this is


@pytest.mark.parametrize(
    ("date_of_birth", "identity_status", "code"),
    [
        ("1985-03-15", "not_found", "NOT_FOUND"),
        ("03/14/1985", "not_checked", "INVALID_ARGUMENT"),
    ],
)
def test_failed_identity_lookup_does_not_verify_anyone(ehr, date_of_birth, identity_status, code):
    state = ConversationState(call_id="call_test", caller_phone=LUIS_PHONE)
    runner = ToolRunner(ehr, state, lambda: NOW)
    result = runner.execute(
        "verify_identity",
        {"first_name": "Maria", "last_name": "Garcia", "date_of_birth": date_of_birth},
    )
    assert result["status"] == "failed"
    assert result["identity_status"] == identity_status
    assert result["error"]["code"] == code
    assert state.verified_patient is None
    # Not even Luis, whose phone this is: patient-scoped tools stay locked.
    blocked = runner.execute("list_my_appointments", {})
    assert blocked["error"]["code"] == "VERIFICATION_REQUIRED"


def test_ambiguous_identity_is_reported_explicitly(ehr):
    # A second record with Maria's name and DOB (and no phone) makes the match ambiguous.
    from care_agent.ehr.models import Patient

    with ehr:
        repo.insert_patient(
            ehr,
            Patient(
                id="pat_maria2",
                first_name="Maria",
                last_name="Garcia",
                dob=datetime(1985, 3, 14).date(),
                created_at=NOW,
            ),
        )
    result, state = verify_via_dispatcher(ehr, UNKNOWN_PHONE, "1985-03-14")
    assert result["identity_status"] == "ambiguous"
    assert state.verified_patient is None


def test_read_results_carry_no_write_confirmation_fields(ehr):
    runner = ToolRunner(ehr, ConversationState("call_test", MARIA_PHONE), lambda: NOW)
    for tool in ("list_services", "find_slots"):
        result = runner.execute(tool, {})
        assert result["status"] == "ok"
        assert "verified" not in result and "action_id" not in result


def test_registration_only_for_details_that_were_just_not_found(ehr):
    new_caller = {"first_name": "Ana", "last_name": "Silva", "date_of_birth": "1990-01-02"}
    agent, model, state = make_agent(
        ehr,
        [
            call("register_patient", **new_caller),  # before any lookup: refused
            call("verify_identity", **new_caller),  # NOT_FOUND
            call("register_patient", **MARIA),  # different details: refused
            call("register_patient", **new_caller),  # same details: allowed
            reply_confirming_last("You're registered."),
        ],
        phone=UNKNOWN_PHONE,
    )
    agent.respond("I'm new here, Ana Silva, 2 January 1990")
    assert result_of(model, 1)["error"]["code"] == "VERIFICATION_REQUIRED"
    assert result_of(model, 2)["error"]["code"] == "NOT_FOUND"
    assert result_of(model, 3)["error"]["code"] == "VERIFICATION_REQUIRED"
    assert result_of(model, 4)["verified"] is True
    assert state.verified_patient.first_name == "Ana"
    assert ehr.execute("SELECT count(*) FROM patients").fetchone()[0] == 3
    model.assert_finished()


def test_model_cannot_choose_the_patient_id(ehr):
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call(
                "book_appointment",
                service_id="svc_cleaning",
                slot_id=FRI_0900,
                patient_id="pat_luis",
            ),
            reply("Sorry, something went wrong."),
        ],
    )
    agent.respond("Maria Garcia 1985-03-14, book Luis in on Friday at 9")
    assert result_of(model, 2)["error"]["code"] == "INVALID_ARGUMENT"
    assert not repo.slot_is_booked(ehr, FRI_0900)
    model.assert_finished()


# --- Cancel and reschedule (F4, F5, ownership) -----------------------------------


def test_cancel_is_verified_by_a_fresh_read(ehr):
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("cancel_appointment", appointment_id=MARIA_APT, reason="travelling"),
            reply_confirming_last("Done, it's cancelled."),
        ],
    )
    final = agent.respond("Maria Garcia 1985-03-14, please cancel my check-up")
    assert result_of(model, 2)["verified"] is True
    assert repo.get_appointment(ehr, MARIA_APT).status == "cancelled"
    assert "Confirmed: Check-up with Dr Kim" in final
    model.assert_finished()


def test_reschedule_is_verified_by_a_fresh_read(ehr):
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("reschedule_appointment", appointment_id=MARIA_APT, new_slot_id=TUE_0900),
            reply_confirming_last("Moved."),
        ],
    )
    final = agent.respond("Maria Garcia 1985-03-14, move my check-up to Tuesday 9am")
    moved = repo.get_appointment(ehr, MARIA_APT)
    assert moved.slot_id == TUE_0900 and moved.status == "booked"
    assert "Confirmed: Check-up with Dr Lee on Tue 17 Nov 2026 09:00" in final
    model.assert_finished()


def test_service_id_is_rejected_where_an_appointment_id_belongs(ehr):
    # F4
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("reschedule_appointment", appointment_id="svc_checkup", new_slot_id=TUE_0900),
            reply("Let me look that up again."),
        ],
    )
    before = repo.get_appointment(ehr, MARIA_APT)
    agent.respond("Maria Garcia 1985-03-14, move my check-up to Tuesday")
    assert result_of(model, 2)["error"]["code"] == "INVALID_ID"
    assert repo.get_appointment(ehr, MARIA_APT) == before
    model.assert_finished()


def test_cannot_cancel_another_patients_appointment(ehr):
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **LUIS),
            call("cancel_appointment", appointment_id=MARIA_APT),
            reply("I couldn't find that appointment."),
        ],
        phone=LUIS_PHONE,
    )
    agent.respond("Luis Garcia 1983-07-02, cancel my wife's check-up")
    assert result_of(model, 2)["error"]["code"] == "NOT_FOUND"
    assert repo.get_appointment(ehr, MARIA_APT).status == "booked"
    model.assert_finished()


def test_appointment_cancelled_elsewhere_is_reported_not_acted_on(ehr):
    # F5: the agent listed the appointment, then the clinic cancelled it.
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("list_my_appointments"),
            reply("You have a check-up on Monday. Cancel it?"),
            call("cancel_appointment", appointment_id=MARIA_APT),
            reply("It looks like it was already cancelled."),
        ],
    )
    agent.respond("Maria Garcia 1985-03-14, what do I have booked?")
    seen = repo.get_appointment(ehr, MARIA_APT)
    external = service.cancel_appointment(ehr, MARIA_APT, expected_version=seen.version, now=NOW)
    agent.respond("Yes, cancel it")
    assert result_of(model, 4)["error"]["code"] == "ALREADY_CANCELLED"
    assert repo.get_appointment(ehr, MARIA_APT) == external  # not touched again
    model.assert_finished()


# --- Faults and truthful replies (F1, F2) ----------------------------------------


def test_booking_timeout_after_commit_is_reconciled_without_duplicate(ehr):
    faults = FaultPlan({"book_appointment": [FaultMode.TIMEOUT_AFTER_COMMIT]})
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("book_appointment", service_id="svc_cleaning", slot_id=FRI_0900),
            reply_confirming_last("You're booked."),
        ],
        faults=faults,
    )
    before = booked_count(ehr)
    final = agent.respond("Maria Garcia 1985-03-14, cleaning Friday 9am")
    assert result_of(model, 2)["verified"] is True
    assert booked_count(ehr) == before + 1
    assert "Confirmed: Cleaning with Dr Lee" in final
    model.assert_finished()


def test_transient_booking_timeout_is_retried_with_the_same_action(ehr):
    faults = FaultPlan({"book_appointment": [FaultMode.TIMEOUT_BEFORE_COMMIT]})
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("book_appointment", service_id="svc_cleaning", slot_id=FRI_0900),
            reply_confirming_last("You're booked."),
        ],
        faults=faults,
    )
    before = booked_count(ehr)
    agent.respond("Maria Garcia 1985-03-14, cleaning Friday 9am")
    result = result_of(model, 2)
    assert result["verified"] is True
    assert booked_count(ehr) == before + 1
    # One logical action, one idempotency record, however many attempts it took.
    keys = ehr.execute("SELECT action_id FROM idempotency_keys").fetchall()
    assert [k["action_id"] for k in keys] == [result["action_id"]]
    model.assert_finished()


def test_transient_cancel_timeout_is_retried(ehr):
    faults = FaultPlan({"cancel_appointment": [FaultMode.TIMEOUT_BEFORE_COMMIT]})
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("cancel_appointment", appointment_id=MARIA_APT),
            reply_confirming_last("Cancelled."),
        ],
        faults=faults,
    )
    agent.respond("Maria Garcia 1985-03-14, cancel my check-up")
    assert result_of(model, 2)["verified"] is True
    assert repo.get_appointment(ehr, MARIA_APT).status == "cancelled"
    model.assert_finished()


def test_booking_that_never_commits_cannot_be_claimed(ehr):
    # F1: every attempt times out before commit, and the model tries to say it worked.
    faults = FaultPlan({"book_appointment": [FaultMode.TIMEOUT_BEFORE_COMMIT] * 3})
    agent, model, state = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("book_appointment", service_id="svc_cleaning", slot_id=FRI_0900),
            reply_claiming_last_action("You're booked for Friday at 9!"),
            reply("Sorry, the booking did not go through. Shall I ask staff to call you?"),
        ],
        faults=faults,
    )
    final = agent.respond("Maria Garcia 1985-03-14, cleaning Friday 9am")
    assert result_of(model, 2)["status"] == "failed"
    assert result_of(model, 3)["status"] == "rejected"  # the lie was not delivered
    assert "did not go through" in final
    assert "Confirmed" not in final
    assert not repo.slot_is_booked(ehr, FRI_0900)
    assert all(
        e.status != "verified"
        for e in state.ledger.entries.values()
        if e.operation == "book_appointment"
    )
    model.assert_finished()


def test_cancel_that_never_commits_falls_back_to_the_truth(ehr):
    # The written question: the patient must not hear "cancelled" when it is not.
    faults = FaultPlan({"cancel_appointment": [FaultMode.TIMEOUT_BEFORE_COMMIT] * 3})
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("cancel_appointment", appointment_id=MARIA_APT),
            reply_claiming_last_action("Your appointment has been cancelled."),
            reply_claiming_last_action("All done, it is cancelled."),
        ],
        faults=faults,
    )
    final = agent.respond("Maria Garcia 1985-03-14, cancel my check-up")
    assert repo.get_appointment(ehr, MARIA_APT).status == "booked"
    assert "The cancellation did not go through." in final
    assert claimed_operations(final) == set()
    model.assert_finished()


def test_cancel_timeout_after_commit_is_verified(ehr):
    faults = FaultPlan({"cancel_appointment": [FaultMode.TIMEOUT_AFTER_COMMIT]})
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("cancel_appointment", appointment_id=MARIA_APT),
            reply_confirming_last("Cancelled."),
        ],
        faults=faults,
    )
    agent.respond("Maria Garcia 1985-03-14, cancel my check-up")
    assert result_of(model, 2)["verified"] is True
    assert repo.get_appointment(ehr, MARIA_APT).status == "cancelled"
    model.assert_finished()


def test_escalation_is_verified_and_not_duplicated(ehr):
    # F2: an error after commit plus a second request still leaves one escalation.
    faults = FaultPlan({"create_escalation": [FaultMode.ERROR_AFTER_COMMIT]})
    agent, model, _ = make_agent(
        ehr,
        [
            call("escalate_to_staff", reason="wants to talk to a person"),
            reply_confirming_last("I've passed this on to the team."),
            call("escalate_to_staff", reason="asked again"),
            reply_confirming_last("The team has been notified."),
        ],
        phone=UNKNOWN_PHONE,
        faults=faults,
    )
    first = agent.respond("I want to speak to a human")
    agent.respond("Please, a human")
    assert result_of(model, 1)["verified"] is True
    assert "Confirmed: A member of staff has been asked to call you back." in first
    assert ehr.execute("SELECT count(*) FROM escalations").fetchone()[0] == 1
    model.assert_finished()


def test_plain_text_success_claim_without_an_action_is_replaced(ehr):
    agent, model, _ = make_agent(ehr, [say("Great news, you're booked for Tuesday at 10!")])
    final = agent.respond("Book me for Tuesday")
    assert claimed_operations(final) == set()
    assert "trouble" in final
    model.assert_finished()


def test_reply_confirming_an_unknown_action_is_rejected(ehr):
    agent, model, _ = make_agent(
        ehr,
        [
            reply("Your appointment is booked.", ["act_made_up"]),
            reply("I haven't booked anything yet. Which day suits you?"),
        ],
    )
    final = agent.respond("Am I booked?")
    assert result_of(model, 1)["status"] == "rejected"
    assert final == "I haven't booked anything yet. Which day suits you?"
    model.assert_finished()


# --- Robustness ------------------------------------------------------------------


class FailingOnce(ScriptedModel):
    def __init__(self, steps):
        super().__init__(steps)
        self.failed = False

    def generate(self, contents):
        if not self.failed:
            self.failed = True
            self.seen.append(list(contents))
            raise RuntimeError("network down")
        return super().generate(contents)


def test_model_error_gives_a_fallback_and_the_conversation_continues(ehr):
    state = ConversationState(call_id="call_test", caller_phone=MARIA_PHONE)
    model = FailingOnce([reply("Hello again, how can I help?")])
    agent = Agent(model, ToolRunner(ehr, state, lambda: NOW), state)
    assert "trouble" in agent.respond("Hello?")
    assert isinstance(agent.last_model_error, RuntimeError)
    assert [c.role for c in agent.history] == ["user", "model"]
    assert agent.respond("Hello?") == "Hello again, how can I help?"
    model.assert_finished()


def test_tool_loop_is_bounded(ehr):
    agent, model, _ = make_agent(ehr, [call("list_services")] * MAX_MODEL_CALLS)
    final = agent.respond("What do you offer?")
    assert "trouble" in final
    model.assert_finished()


# --- Claim guard -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("You're booked for Friday.", {"book_appointment"}),
        ("Your appointment has been cancelled.", {"cancel_appointment"}),
        ("I've moved it to Tuesday.", {"reschedule_appointment"}),
        ("I have escalated this to the team.", {"create_escalation"}),
        ("Your appointment has not been cancelled.", set()),
        ("It hasn't been booked yet.", set()),
        ("Would you like me to book it?", set()),
        ("The booking did not go through.", set()),
    ],
)
def test_success_wording_detector(message, expected):
    assert claimed_operations(message) == expected


def test_guard_appends_confirmations_from_the_ledger():
    ledger = OutcomeLedger()
    ledger.record(LedgerEntry("act_1", "book_appointment", "verified", "Cleaning on Fri"))
    decision = check_reply("All set, you're booked.", ["act_1"], ledger)
    assert decision.ok
    assert decision.text == "All set, you're booked.\nConfirmed: Cleaning on Fri"


def test_guard_rejects_claims_beyond_what_was_confirmed():
    ledger = OutcomeLedger()
    ledger.record(LedgerEntry("act_1", "book_appointment", "verified", "Cleaning on Fri"))
    ledger.record(LedgerEntry("act_2", "cancel_appointment", "failed"))
    decision = check_reply("Booked, and your old one has been cancelled.", ["act_1"], ledger)
    assert not decision.ok
    decision = check_reply("Cancelled.", ["act_2"], ledger)
    assert not decision.ok


# --- Demo seed data --------------------------------------------------------------


def test_demo_seed_is_deterministic_and_on_weekdays():
    assert demo_slots(NOW) == demo_slots(NOW)
    assert all(start.weekday() < 5 and start > NOW for _, _, start, _ in demo_slots(NOW))


def test_demo_seed_gives_maria_one_booked_appointment(ehr):
    appointments = repo.list_appointments_for_patient(ehr, "pat_maria")
    assert [(a.id, a.status) for a in appointments] == [(MARIA_APT, "booked")]


# --- IMP-002: agent actions vs EHR observations ------------------------------------------

OTHER_APT = "apt_other"


def ledger_with(*entries, observed=None):
    ledger = OutcomeLedger()
    for entry in entries:
        ledger.record(entry)
    for appointment_id, status in (observed or {}).items():
        ledger.observe(appointment_id, status)
    return ledger


VERIFIED_CANCEL = LedgerEntry(
    "act_c", "cancel_appointment", "verified", "Check-up ... is cancelled.", MARIA_APT
)
FAILED_CANCEL = LedgerEntry("act_f", "cancel_appointment", "failed", None, MARIA_APT)


def test_verified_cancellation_supports_first_person_claim():
    ledger = ledger_with(VERIFIED_CANCEL, observed={MARIA_APT: "cancelled"})
    assert check_reply("I've cancelled it.", ["act_c"], ledger).ok
    # Restating it later without the ID is still backed: one verified cancellation.
    assert check_reply("As I said, I've cancelled your check-up.", [], ledger).ok


def test_fresh_ehr_observation_supports_already_cancelled_state():
    ledger = ledger_with(observed={MARIA_APT: "cancelled"})
    for message in (
        "It is already cancelled.",
        "Your appointment has already been cancelled, so I couldn't reschedule it.",
    ):
        assert check_reply(message, [], ledger).ok, message


def test_fresh_ehr_observation_does_not_support_first_person_claim():
    ledger = ledger_with(observed={MARIA_APT: "cancelled"})
    decision = check_reply("I've cancelled it.", [], ledger)
    assert not decision.ok
    assert "no verified cancel_appointment action" in decision.problems[0]


def test_failed_cancellation_supports_no_cancellation_claim():
    ledger = ledger_with(FAILED_CANCEL, observed={MARIA_APT: "booked"})
    for message in ("I've cancelled it.", "Your check-up has been cancelled.", "It is cancelled."):
        assert not check_reply(message, [], ledger).ok, message
    assert not check_reply("It is cancelled.", ["act_f"], ledger).ok


def test_booked_observation_never_supports_a_claim():
    # A "booked" read can go stale (F5); only cancelled observations count as evidence.
    ledger = ledger_with(observed={MARIA_APT: "booked"})
    assert not check_reply("Your check-up is booked for Monday.", [], ledger).ok


def test_ambiguous_evidence_requires_the_action_id():
    first = VERIFIED_CANCEL
    second = LedgerEntry(
        "act_d", "cancel_appointment", "verified", "Other ... is cancelled.", OTHER_APT
    )
    ledger = ledger_with(first, second, observed={MARIA_APT: "cancelled", OTHER_APT: "cancelled"})
    decision = check_reply("It has been cancelled.", [], ledger)
    assert not decision.ok
    assert "more than one record" in decision.problems[0]
    assert check_reply("It has been cancelled.", ["act_c"], ledger).ok


def test_claim_kinds_are_classified():
    from care_agent.agent.guard import classify_claims

    assert classify_claims("I've cancelled it.") == ({"cancel_appointment"}, set())
    assert classify_claims("It has already been cancelled.") == (set(), {"cancel_appointment"})
    assert classify_claims("I've gone ahead and booked a new check-up.") == (
        {"book_appointment"},
        set(),
    )
    for neither in (
        "I haven't cancelled it yet.",
        "It has not been cancelled.",
        "I tried to cancel your check-up, but it didn't go through.",
        "I'll cancel it now.",
    ):
        assert classify_claims(neither) == (set(), set()), neither


def test_tools_record_observations_and_record_ids(ehr):
    state = ConversationState(call_id="call_test", caller_phone=MARIA_PHONE)
    runner = ToolRunner(ehr, state, lambda: NOW)
    runner.execute("verify_identity", MARIA)
    runner.execute("list_my_appointments", {})
    assert state.ledger.observed == {MARIA_APT: "booked"}
    result = runner.execute("cancel_appointment", {"appointment_id": MARIA_APT})
    assert state.ledger.observed == {MARIA_APT: "cancelled"}
    assert state.ledger.get(result["action_id"]).record_id == MARIA_APT


def test_already_cancelled_reply_is_delivered_after_external_cancel(ehr):
    # Run 20261112T181154Z, E5 turn 1: the clinic cancelled the appointment; the agent's
    # truthful explanation was rejected and it then booked something unrequested.
    message = (
        "I'm sorry, Maria, your appointment has already been cancelled, so we couldn't "
        "reschedule it directly. Would you like me to book a new appointment on Tuesday "
        "17 November at 09:00 instead, or would you like a staff member to call you back?"
    )
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("list_my_appointments"),
            reply("You have a check-up on Monday."),
            call("list_my_appointments"),
            call("reschedule_appointment", appointment_id=MARIA_APT, new_slot_id=TUE_0900),
            reply(message),
        ],
    )
    agent.respond("Maria Garcia 1985-03-14, what do I have?")
    seen = repo.get_appointment(ehr, MARIA_APT)
    service.cancel_appointment(ehr, MARIA_APT, expected_version=seen.version, now=NOW)
    final = agent.respond("Please move my check-up to Tuesday 17 November at 09:00.")
    assert result_of(model, 5)["error"]["code"] == "ALREADY_CANCELLED"
    assert final == message  # delivered first time, no rejection
    model.assert_finished()


def test_first_person_claim_after_external_cancel_is_rejected(ehr):
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("list_my_appointments"),
            reply("I've cancelled your check-up."),  # the clinic did, not the agent
            reply("Your check-up is already cancelled."),
        ],
    )
    seen = repo.get_appointment(ehr, MARIA_APT)
    service.cancel_appointment(ehr, MARIA_APT, expected_version=seen.version, now=NOW)
    final = agent.respond("Maria Garcia 1985-03-14, is my check-up still on?")
    assert result_of(model, 3)["status"] == "rejected"
    assert final == "Your check-up is already cancelled."
    model.assert_finished()


def test_truthful_restatement_after_own_cancellation_is_not_rejected(ehr):
    # Run 20261112T181154Z, E4 turn 1: the agent had cancelled and verified in turn 0;
    # restating it without the action ID was rejected.
    restated = (
        "Your check-up appointment has already been cancelled. "
        "Is there anything else I can help you with today?"
    )
    agent, model, _ = make_agent(
        ehr,
        [
            call("verify_identity", **MARIA),
            call("cancel_appointment", appointment_id=MARIA_APT),
            reply_confirming_last("I have successfully cancelled your check-up."),
            reply(restated),
        ],
    )
    agent.respond("Maria Garcia 1985-03-14. Please cancel my check-up.")
    assert agent.respond("Yes, please cancel it.") == restated
    model.assert_finished()
