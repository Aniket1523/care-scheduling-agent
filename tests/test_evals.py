"""M3: the evaluation harness, driven by scripted models (no network, no API key).

The scripted "good agent" conversations show that every scenario can pass and
that grading reads the EHR. Deliberately broken behaviour shows that failures
are caught, reported and gated.
"""

from __future__ import annotations

import json

import pytest

from agent_fakes import ScriptedModel, call, reply, reply_confirming_last
from care_agent.agent.state import OutcomeLedger
from care_agent.evals.grading import claimed_by_agent
from care_agent.evals.runner import run_scenario
from care_agent.evals.scenarios import (
    FRI_0900_LEE,
    FRI_1000_KIM,
    MARIA_CHECKUP,
    SCENARIOS,
    SCENARIOS_BY_ID,
)
from care_agent.evals.suite import EXIT_INCOMPLETE, EXIT_OK, EXIT_REGRESSION, run_eval

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


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
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
