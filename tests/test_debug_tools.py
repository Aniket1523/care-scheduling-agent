"""Opt-in tool-call diagnostics (CARE_AGENT_DEBUG_TOOLS=1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_fakes import ScriptedModel, call, reply, say
from care_agent.agent.loop import Agent
from care_agent.agent.state import ConversationState
from care_agent.agent.tools import ToolRunner
from care_agent.ehr import repository as repo
from care_agent.ehr.db import connect, init_db
from care_agent.ehr.seed import seed_demo_data

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
LUIS_PHONE = "+15550100002"
SECRET = "test-key-must-not-appear"


@pytest.fixture
def ehr(tmp_path):
    conn = connect(tmp_path / "debug.sqlite3")
    init_db(conn)
    seed_demo_data(conn, NOW)
    yield conn
    conn.close()


def run_f3_turn(conn):
    state = ConversationState(call_id="call_test", caller_phone=LUIS_PHONE)
    model = ScriptedModel(
        [
            call(
                "verify_identity",
                first_name="Maria",
                last_name="Garcia",
                date_of_birth="14 March 1985",
            ),
            reply("Thanks Maria, you're verified."),
        ]
    )
    Agent(model, ToolRunner(conn, state, lambda: NOW), state).respond(
        "Maria Garcia, 14 March 1985."
    )
    return state


def test_debug_output_is_off_by_default(ehr, capsys, monkeypatch):
    monkeypatch.delenv("CARE_AGENT_DEBUG_TOOLS", raising=False)
    run_f3_turn(ehr)
    assert capsys.readouterr().err == ""


def test_debug_output_traces_the_identity_path(ehr, capsys, monkeypatch):
    monkeypatch.setenv("CARE_AGENT_DEBUG_TOOLS", "1")
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    state = run_f3_turn(ehr)
    err = capsys.readouterr().err

    assert state.verified_patient.id == "pat_maria"  # logging changes nothing
    expected = [
        'model.output kind="tool_calls" tools=["verify_identity"]',
        'model.tool_call tool="verify_identity" args={"first_name": "Maria", '
        '"last_name": "Garcia", "date_of_birth": "14 March 1985"}',
        'tool_runner.received tool="verify_identity"',
        'verify_identity.parse_date raw="14 March 1985" parsed="1985-03-14"',
        'status="matched" method="name_dob" candidate_count=1 patient_id="pat_maria"',
        'tool_runner.result tool="verify_identity" result={"status": "ok"',
        'claim_guard status="delivered"',
    ]
    for line in expected:
        assert line in err, line
    assert SECRET not in err
    assert "scheduling assistant" not in err  # no system prompt


def test_debug_output_reports_plain_text_replies(ehr, capsys, monkeypatch):
    monkeypatch.setenv("CARE_AGENT_DEBUG_TOOLS", "1")
    state = ConversationState(call_id="call_test", caller_phone=LUIS_PHONE)
    model = ScriptedModel([say("Hello, how can I help?")])
    Agent(model, ToolRunner(ehr, state, lambda: NOW), state).respond("Hi")
    err = capsys.readouterr().err
    assert 'model.output kind="text" tools=[]' in err
    assert "Hello, how can I help?" not in err  # reply text is conversation, not logged


def test_debug_output_reports_tool_exceptions(ehr, capsys, monkeypatch):
    monkeypatch.setenv("CARE_AGENT_DEBUG_TOOLS", "1")

    def broken(conn):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(repo, "list_services", broken)
    runner = ToolRunner(ehr, ConversationState("call_test", LUIS_PHONE), lambda: NOW)
    with pytest.raises(RuntimeError):
        runner.execute("list_services", {})
    err = capsys.readouterr().err
    assert (
        'tool_runner.exception tool="list_services" error="RuntimeError: database unavailable"'
        in err
    )
