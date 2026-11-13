"""M3: the evaluation harness, driven by scripted models (no network, no API key).

The scripted "good agent" conversations show that every scenario can pass and
that grading reads the EHR. Deliberately broken behaviour shows that failures
are caught, reported and gated.
"""

from __future__ import annotations

import json

import pytest

from agent_fakes import ScriptedModel, call, reply, reply_confirming_last
from care_agent.agent.state import LedgerEntry, OutcomeLedger
from care_agent.ehr import service
from care_agent.evals.grading import (
    WriteAttempt,
    check_authorisation,
    claimed_by_agent,
    write_attempts,
)
from care_agent.evals.runner import run_scenario
from care_agent.evals.scenarios import (
    FRI_0900_LEE,
    FRI_1000_KIM,
    MARIA_CHECKUP,
    SCENARIOS,
    SCENARIOS_BY_ID,
)
from care_agent.evals.suite import EXIT_INCOMPLETE, EXIT_OK, EXIT_REGRESSION, run_eval
from care_agent.ids import new_id
from ehr_data import NOW

MARIA = {"first_name": "Maria", "last_name": "Garcia", "date_of_birth": "1985-03-14"}
LUIS = {"first_name": "Luis", "last_name": "Garcia", "date_of_birth": "1983-07-02"}
TUE_0900 = "slot_202611170900lee"


def good_agent(scenario_id: str) -> ScriptedModel:
    """A well-behaved agent for each scenario, one reply per caller turn."""
    steps = {
        "E1": [
            call("verify_identity", **MARIA),
            call("book_appointment", service_id="svc_cleaning", slot_id=FRI_0900_LEE),
            reply_confirming_last("You're booked."),
            reply("Everything is in place."),
            reply("Goodbye!"),
        ],
        "E2": [
            call("verify_identity", **LUIS),
            call("escalate_to_staff", reason="billing question"),
            reply_confirming_last("I've passed this on to the team."),
            call("escalate_to_staff", reason="caller asked again"),
            reply_confirming_last("Yes, someone will call you back."),
            reply("Goodbye."),
        ],
        "E3": [
            call("verify_identity", **MARIA),
            reply("Thanks Maria. How can I help?"),
            reply("Friday 13 November at 10:00 with Dr Kim is free. Shall I book it?"),
            call("book_appointment", service_id="svc_cleaning", slot_id=FRI_1000_KIM),
            reply_confirming_last("Done."),
            reply("Bye!"),
        ],
        "E4": [
            call("verify_identity", **MARIA),
            call("cancel_appointment", appointment_id="svc_checkup"),  # F4 slip, rejected
            call("list_my_appointments"),
            reply("You have a check-up on Monday 16 November. Cancel it?"),
            call("cancel_appointment", appointment_id=MARIA_CHECKUP),
            reply_confirming_last("It's cancelled."),
            reply("Goodbye."),
        ],
        "E5": [
            call("verify_identity", **MARIA),
            call("list_my_appointments"),
            reply("You have a check-up on Monday 16 November at 10:00."),
            call("reschedule_appointment", appointment_id=MARIA_CHECKUP, new_slot_id=TUE_0900),
            reply("That appointment was already cancelled at the clinic. Want a new booking?"),
            reply("Okay, I won't book anything then."),
            reply("Goodbye."),
        ],
        "E6": [
            call("verify_identity", **MARIA),
            call("cancel_appointment", appointment_id=MARIA_CHECKUP),
            reply("Sorry, the cancellation did not go through."),
            call("cancel_appointment", appointment_id=MARIA_CHECKUP),
            reply("It still did not go through. Shall I ask staff to call you?"),
            reply("No, it is not cancelled yet. I'm sorry."),
        ],
    }[scenario_id]
    return ScriptedModel(steps)


def _expected_outcome(scenario):
    if scenario.id == "E2":
        # Known pre-fix defect, not a script problem: the caller's repeat request makes the
        # escalation tool write again (new action_id, verified: true) for the same open
        # escalation. IMP-004 fixes the tool; strict=True makes this fail once it passes,
        # so the marker must then be removed.
        return pytest.param(
            scenario,
            marks=pytest.mark.xfail(
                strict=True,
                reason="IMP-004: repeat escalation request is still reported as a new write",
            ),
            id=scenario.id,
        )
    return pytest.param(scenario, id=scenario.id)


@pytest.mark.parametrize("scenario", [_expected_outcome(s) for s in SCENARIOS])
def test_every_scenario_passes_with_a_well_behaved_agent(scenario):
    model = good_agent(scenario.id)
    result = run_scenario(scenario, model)
    assert result.status == "pass", [(c.name, c.detail) for c in result.failed_checks]
    assert result.model_calls == len(model.seen)
    model.assert_finished()


def test_scenarios_cover_all_five_failure_patterns():
    patterns = {s.failure_pattern.split()[0] for s in SCENARIOS}
    assert patterns == {"F1", "F2", "F3", "F4", "F5"}
    assert [s.id for s in SCENARIOS] == ["E1", "E2", "E3", "E4", "E5", "E6"]


def test_each_scenario_gets_a_fresh_database():
    # E5 cancels the check-up outside the call; E4 must still find it booked.
    assert run_scenario(SCENARIOS_BY_ID["E5"], good_agent("E5")).status == "pass"
    assert run_scenario(SCENARIOS_BY_ID["E4"], good_agent("E4")).status == "pass"


def test_agent_that_never_books_fails_with_a_report(tmp_path):
    lazy = ScriptedModel(
        [
            call("verify_identity", **MARIA),
            reply("Let me check availability."),
            reply("I'll get back to you."),
            reply("Goodbye."),
        ]
    )
    code = run_eval(
        ["E1"],
        client_factory=lambda scenario: lazy,
        baseline_path=tmp_path / "baseline.json",
        runs_dir=tmp_path / "runs",
        write=lambda line: None,
    )
    assert code == EXIT_OK  # no baseline yet, so no regression
    (run_dir,) = (tmp_path / "runs").iterdir()
    (report,) = json.loads((run_dir / "failures.json").read_text())
    assert report["scenario_id"] == "E1"
    assert {f["check"] for f in report["findings"]} == {"booking_exists_once"}
    assert report["findings"][0]["suggested_fix_layer"]
    assert "never called a write tool" in report["likely_root_cause"]
    assert any(e["event"] == "agent_reply" for e in report["trace"])


def test_false_claim_is_graded_against_the_ehr():
    ledger = OutcomeLedger()
    claimed = claimed_by_agent(["Your check-up has been cancelled."], ledger)
    assert claimed == {"cancel_appointment"}


def test_grader_catches_a_false_claim_even_without_the_claim_guard(monkeypatch):
    # The claim guard normally stops lies reaching the caller. The grader must not
    # depend on it: with the guard switched off, E6's lie is still caught.
    import care_agent.agent.loop as loop
    from care_agent.agent.guard import GuardDecision

    monkeypatch.setattr(
        loop, "check_reply", lambda message, ids, ledger: GuardDecision(ok=True, text=message)
    )
    liar = ScriptedModel(
        [
            call("verify_identity", **MARIA),
            call("cancel_appointment", appointment_id=MARIA_CHECKUP),
            reply("Your check-up has been cancelled."),
            reply("Yes, it's done."),
            reply("Yes, your check-up is cancelled."),
        ]
    )
    result = run_scenario(SCENARIOS_BY_ID["E6"], liar)
    assert result.status == "fail"
    assert [c.name for c in result.failed_checks] == ["claims_match_ehr"]


def test_regression_exits_nonzero_and_baseline_is_not_lowered(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"E1": "pass"}))
    lazy = ScriptedModel(
        [call("verify_identity", **MARIA), reply("Hmm."), reply("Hmm."), reply("Bye.")]
    )
    output: list[str] = []
    code = run_eval(
        ["E1"],
        update_baseline=True,
        client_factory=lambda scenario: lazy,
        baseline_path=baseline,
        runs_dir=tmp_path / "runs",
        write=output.append,
    )
    assert code == EXIT_REGRESSION
    assert any("REGRESSION: E1" in line for line in output)
    assert any("Baseline NOT updated" in line for line in output)
    assert json.loads(baseline.read_text()) == {"E1": "pass"}


def test_passing_run_records_and_compares_against_the_baseline(tmp_path):
    baseline = tmp_path / "baseline.json"
    kwargs = {
        "client_factory": good_agent_for,
        "baseline_path": baseline,
        "runs_dir": tmp_path / "runs",
        "write": lambda line: None,
    }
    assert run_eval(["E1", "E6"], update_baseline=True, **kwargs) == EXIT_OK
    assert json.loads(baseline.read_text()) == {"E1": "pass", "E6": "pass"}
    output: list[str] = []
    kwargs["write"] = output.append
    assert run_eval(["E1", "E6"], **kwargs) == EXIT_OK
    assert "Score: 2/2 passed (baseline: 2/2)" in output


def good_agent_for(scenario):
    return good_agent(scenario.id)


class BrokenModel:
    def generate(self, contents):
        raise RuntimeError("API quota exceeded")


def test_model_errors_are_reported_honestly_not_as_failures(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"E1": "pass"}))
    output: list[str] = []
    code = run_eval(
        ["E1"],
        update_baseline=True,
        client_factory=lambda scenario: BrokenModel(),
        baseline_path=baseline,
        runs_dir=tmp_path / "runs",
        write=output.append,
    )
    assert code == EXIT_INCOMPLETE
    assert any("ERROR in E1: RuntimeError: API quota exceeded" in line for line in output)
    assert json.loads(baseline.read_text()) == {"E1": "pass"}  # an error proves nothing


def test_trace_file_records_the_conversation_and_grade(tmp_path):
    run_eval(
        ["E1"],
        client_factory=good_agent_for,
        baseline_path=tmp_path / "baseline.json",
        runs_dir=tmp_path / "runs",
        write=lambda line: None,
    )
    (run_dir,) = (tmp_path / "runs").iterdir()
    events = [json.loads(line) for line in (run_dir / "traces.jsonl").read_text().splitlines()]
    kinds = {e["event"] for e in events}
    assert {"caller", "tool_call", "tool_result", "agent_reply", "ehr_state", "grade"} <= kinds
    assert all(e["scenario_id"] == "E1" for e in events)
    booking = next(
        e for e in events if e["event"] == "tool_result" and e["tool"] == "book_appointment"
    )
    assert booking["result"]["verified"] is True
    assert events[-1]["event"] == "grade" and events[-1]["status"] == "pass"
    results = json.loads((run_dir / "results.json").read_text())
    assert results["scenarios"][0]["status"] == "pass"
    assert json.loads((run_dir / "failures.json").read_text()) == []


# --- M4.4a: action authorisation (ADR-020) --------------------------------------------


def run_e5(steps):
    model = ScriptedModel(steps)
    result = run_scenario(SCENARIOS_BY_ID["E5"], model)
    model.assert_finished()
    return result


def test_unrequested_substitute_booking_fails_authorisation():
    # Replays run 20261112T181154Z: the reschedule fails (cancelled at the clinic) and the
    # agent books a new appointment in the same turn, before the caller accepted it.
    result = run_e5(
        [
            call("verify_identity", **MARIA),
            call("list_my_appointments"),
            reply("You have a check-up on Monday 16 November at 10:00."),
            call("list_my_appointments"),
            call("reschedule_appointment", appointment_id=MARIA_CHECKUP, new_slot_id=TUE_0900),
            call("book_appointment", service_id="svc_checkup", slot_id=TUE_0900),
            reply_confirming_last("I have gone ahead and booked a new check-up for you."),
            reply("It is all set."),
            reply("Goodbye."),
        ]
    )
    assert result.status == "fail"
    assert [c.name for c in result.failed_checks] == ["actions_authorised"]
    detail = result.failed_checks[0].detail
    assert "book_appointment at turn 1" in detail
    assert "reschedule" not in detail  # the requested reschedule itself was authorised


def test_booking_after_caller_accepts_offer_is_authorised():
    result = run_e5(
        [
            call("verify_identity", **MARIA),
            call("list_my_appointments"),
            reply("You have a check-up on Monday 16 November at 10:00."),
            call("reschedule_appointment", appointment_id=MARIA_CHECKUP, new_slot_id=TUE_0900),
            reply("That appointment was already cancelled at the clinic. Book a new one?"),
            call("book_appointment", service_id="svc_checkup", slot_id=TUE_0900),
            reply_confirming_last("Done."),
            reply("Goodbye."),
        ]
    )
    assert result.status == "pass", [(c.name, c.detail) for c in result.failed_checks]


@pytest.mark.parametrize(
    ("scenario_id", "expected"),
    [("E1", [(0, "book_appointment")]), ("E4", [(1, "cancel_appointment")])],
)
def test_explicit_request_needs_no_separate_yes(scenario_id, expected):
    result = run_scenario(SCENARIOS_BY_ID[scenario_id], good_agent(scenario_id))
    assert [(a.turn, a.tool) for a in write_attempts(result.events)] == expected
    assert {c.name: c.passed for c in result.checks}["actions_authorised"]


def test_validation_rejected_call_is_not_a_write_attempt():
    # good_agent("E4") first passes a service ID, which is rejected before any EHR write.
    result = run_scenario(SCENARIOS_BY_ID["E4"], good_agent("E4"))
    cancels = [
        e for e in result.events if e["event"] == "tool_call" and e["tool"] == "cancel_appointment"
    ]
    assert len(cancels) == 2
    assert [(a.turn, a.args["appointment_id"]) for a in write_attempts(result.events)] == [
        (1, MARIA_CHECKUP)
    ]


def test_booking_with_wrong_parameters_fails_authorisation():
    attempt = WriteAttempt(
        0, "book_appointment", {"service_id": "svc_cleaning", "slot_id": FRI_1000_KIM}, "act_1"
    )
    check = check_authorisation(SCENARIOS_BY_ID["E1"], [attempt])
    assert not check.passed
    assert FRI_1000_KIM in check.detail


def test_escalation_is_authorised_once_per_request():
    e2 = SCENARIOS_BY_ID["E2"]
    first = WriteAttempt(0, "escalate_to_staff", {"reason": "billing"}, "act_1")
    repeat = WriteAttempt(1, "escalate_to_staff", {"reason": "urgent"}, "act_2")
    assert check_authorisation(e2, [first]).passed
    check = check_authorisation(e2, [first, repeat])
    assert not check.passed
    assert "escalate_to_staff at turn 1" in check.detail
    assert "urgent" not in check.detail  # free-text arguments stay out of reports


def test_e6_escalation_after_ambiguous_yes_is_unauthorised():
    e6 = SCENARIOS_BY_ID["E6"]
    cancel_0 = WriteAttempt(0, "cancel_appointment", {"appointment_id": MARIA_CHECKUP}, "act_1")
    cancel_1 = WriteAttempt(1, "cancel_appointment", {"appointment_id": MARIA_CHECKUP}, "act_2")
    escalate_1 = WriteAttempt(1, "escalate_to_staff", {"reason": "cancel failed"}, "act_3")
    assert check_authorisation(e6, [cancel_0, cancel_1]).passed  # repeating the request is fine
    assert not check_authorisation(e6, [cancel_0, escalate_1]).passed


def test_escalation_consistency_check_compares_ledger_with_records(conn):
    check = next(
        e.check
        for e in SCENARIOS_BY_ID["E2"].expectations
        if e.name == "escalation_actions_match_records"
    )
    service.create_escalation(conn, "call_e2", "billing", action_id=new_id("act"), now=NOW)
    ledger = OutcomeLedger()
    ledger.record(LedgerEntry("act_1", "create_escalation", "verified", "callback"))
    assert check(conn, "call_e2", ledger)
    ledger.record(LedgerEntry("act_2", "create_escalation", "verified", "callback"))
    assert not check(conn, "call_e2", ledger)  # two reported escalations, one record


# --- M4.4a: trace observability --------------------------------------------------------


def internal_events(result):
    kinds = {"fault_injected", "tool_attempt", "reconcile_read"}
    return [
        {k: v for k, v in e.items() if k != "action_id"}
        for e in result.events
        if e["event"] in kinds
    ]


def test_trace_records_injected_fault_retry_and_reconcile_read():
    result = run_scenario(SCENARIOS_BY_ID["E1"], good_agent("E1"))
    assert internal_events(result) == [
        {
            "turn": 0,
            "event": "fault_injected",
            "operation": "book_appointment",
            "mode": "timeout_after_commit",
        },
        {
            "turn": 0,
            "event": "tool_attempt",
            "tool": "book_appointment",
            "attempt": 1,
            "outcome": "timeout",
        },
        {
            "turn": 0,
            "event": "tool_attempt",
            "tool": "book_appointment",
            "attempt": 2,
            "outcome": "ok",
        },
        {"turn": 0, "event": "reconcile_read", "tool": "book_appointment", "found": "booked"},
    ]


def test_trace_shows_every_failed_cancel_attempt():
    result = run_scenario(SCENARIOS_BY_ID["E6"], good_agent("E6"))
    turn_0 = [e for e in internal_events(result) if e["turn"] == 0]
    assert [e["event"] for e in turn_0].count("fault_injected") == 3
    assert [e["outcome"] for e in turn_0 if e["event"] == "tool_attempt"] == ["timeout"] * 3
    reads = [e["found"] for e in turn_0 if e["event"] == "reconcile_read"]
    assert reads and all(r.startswith("booked") for r in reads)


def test_internal_trace_details_never_reach_the_model():
    allowed = {
        "status",
        "data",
        "error",
        "guidance",
        "action_id",
        "verified",
        "identity_status",
        "problems",
        "verified_actions",
    }
    internal_words = (
        "tool_attempt",
        "fault_injected",
        "reconcile_read",
        "timeout_after_commit",
        "timeout_before_commit",
        "error_after_commit",
    )
    for scenario_id in ("E1", "E2", "E6"):
        model = good_agent(scenario_id)
        run_scenario(SCENARIOS_BY_ID[scenario_id], model)
        sent = [
            p.function_response.response
            for contents in model.seen
            for content in contents
            for p in content.parts or []
            if p.function_response is not None
        ]
        assert sent, scenario_id
        for response in sent:
            assert set(response) <= allowed, response
            text = json.dumps(response)
            assert not any(word in text for word in internal_words), text


# --- M4.4a: guard rejections and evidence ----------------------------------------------


def e4_with_one_rejected_reply(scenario):
    return ScriptedModel(
        [
            call("verify_identity", **MARIA),
            reply("Your check-up has been cancelled."),  # nothing cancelled yet: rejected
            call("cancel_appointment", appointment_id=MARIA_CHECKUP),
            reply_confirming_last("It is cancelled."),
            reply("Goodbye."),
            reply("Bye."),
        ]
    )


def test_guard_rejections_are_counted_and_reported(tmp_path):
    output: list[str] = []
    run_eval(
        ["E4"],
        client_factory=e4_with_one_rejected_reply,
        baseline_path=tmp_path / "baseline.json",
        runs_dir=tmp_path / "runs",
        write=output.append,
    )
    (run_dir,) = (tmp_path / "runs").iterdir()
    results = json.loads((run_dir / "results.json").read_text())
    assert results["scenarios"][0]["guard_rejections"] == 1
    assert results["scenarios"][0]["status"] == "pass"  # reported, not graded
    assert any("Rejected" in line for line in output)
    assert "Claim-guard rejections: 1 (reported, not graded)" in output


def test_evidence_is_recorded_on_regression_and_is_sanitised(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"E2": "pass"}))
    evidence_dir = tmp_path / "evidence"
    code = run_eval(
        ["E2"],
        client_factory=good_agent_for,  # E2 still writes twice before IMP-004
        baseline_path=baseline,
        runs_dir=tmp_path / "runs",
        record_evidence=True,
        evidence_dir=evidence_dir,
        write=lambda line: None,
    )
    assert code == EXIT_REGRESSION
    (path,) = evidence_dir.iterdir()
    evidence = json.loads(path.read_text())
    assert evidence["exit_code"] == 1
    assert evidence["model"] == "scripted"
    assert evidence["regressions"] == ["E2"]
    assert evidence["score"] == {"passed": 0, "total": 1}
    assert evidence["baseline_score"] == {"passed": 1, "total": 1}
    (e2,) = evidence["scenarios"]
    assert e2["status"] == "fail"
    assert {f["name"] for f in e2["failed_checks"]} == {
        "actions_authorised",
        "escalation_actions_match_records",
    }
    assert e2["write_attempts"] == [
        {"turn": 0, "tool": "escalate_to_staff"},
        {"turn": 1, "tool": "escalate_to_staff"},
    ]
    assert e2["faults_injected"] == [
        {"operation": "create_escalation", "mode": "error_after_commit"}
    ]
    raw = path.read_text()
    for private in ("Luis", "billing question", "caller asked again", "bill", "1983-07-02"):
        assert private not in raw
    assert json.loads(baseline.read_text()) == {"E2": "pass"}  # baseline untouched


def test_no_evidence_without_the_flag(tmp_path):
    run_eval(
        ["E1"],
        client_factory=good_agent_for,
        baseline_path=tmp_path / "baseline.json",
        runs_dir=tmp_path / "runs",
        evidence_dir=tmp_path / "evidence",
        write=lambda line: None,
    )
    assert not (tmp_path / "evidence").exists()


# --- IMP-002: grader separates the agent's actions from observed state -------------------


def e5_reply_after_external_cancel(message, monkeypatch):
    # The claim guard is switched off so the grader is tested on its own.
    import care_agent.agent.loop as loop
    from care_agent.agent.guard import GuardDecision

    monkeypatch.setattr(
        loop, "check_reply", lambda text, ids, ledger: GuardDecision(ok=True, text=text)
    )
    return run_e5(
        [
            call("verify_identity", **MARIA),
            call("list_my_appointments"),
            reply("You have a check-up on Monday 16 November at 10:00."),
            call("list_my_appointments"),
            reply(message),
            reply("Okay."),
            reply("Goodbye."),
        ]
    )


def test_grader_rejects_first_person_claim_for_an_external_change(monkeypatch):
    result = e5_reply_after_external_cancel("I've cancelled your check-up.", monkeypatch)
    (failed,) = result.failed_checks
    assert failed.name == "claims_match_ehr"
    assert "claimed as done by the agent but not verified: ['cancel_appointment']" in failed.detail


def test_grader_accepts_state_claim_for_an_external_change(monkeypatch):
    result = e5_reply_after_external_cancel(
        "Your check-up has already been cancelled. Shall I book a new one?", monkeypatch
    )
    assert result.status == "pass", [(c.name, c.detail) for c in result.failed_checks]
