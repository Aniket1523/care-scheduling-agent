"""M2: the chat session wiring and the Gemini client configuration (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_fakes import ScriptedModel, call, reply, reply_confirming_last
from care_agent.agent.gemini import GeminiClient
from care_agent.agent.tools import TOOL_DECLARATIONS
from care_agent.chat import EXIT_OK, run_chat
from care_agent.config import LLMSettings

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


def test_chat_session_end_to_end_with_scripted_model():
    model = ScriptedModel(
        [
            reply("Hello! What is your full name and date of birth?"),
            call(
                "verify_identity",
                first_name="Maria",
                last_name="Garcia",
                date_of_birth="1985-03-14",
            ),
            call("book_appointment", service_id="svc_cleaning", slot_id="slot_202611130900lee"),
            reply_confirming_last("You're booked."),
        ]
    )
    inputs = iter(["Hi", "Maria Garcia 1985-03-14, cleaning Friday 9am", "quit"])
    output: list[str] = []

    code = run_chat(
        "+1 (555) 010-0001",
        client=model,
        read=lambda prompt: next(inputs),
        write=output.append,
        clock=lambda: NOW,
    )

    assert code == EXIT_OK
    assert "simulated call from +15550100001" in output[0]
    assert output[1] == "Agent: Hello! What is your full name and date of birth?"
    assert "Confirmed: Cleaning with Dr Lee on Fri 13 Nov 2026 09:00" in output[2]
    assert output[-1] == "Call ended."
    model.assert_finished()


def test_gemini_client_disables_automatic_function_calling():
    settings = LLMSettings.from_env({"LLM_API_KEY": "test-key-not-real"})
    client = GeminiClient(settings, "system prompt", TOOL_DECLARATIONS)  # no network call
    assert client.model == "gemini-3.1-flash-lite"
    assert client.config.automatic_function_calling.disable is True
    declared = [d.name for d in client.config.tools[0].function_declarations]
    assert declared == [d["name"] for d in TOOL_DECLARATIONS]
    # No tool lets the model choose a patient or supply the caller's phone.
    for declaration in TOOL_DECLARATIONS:
        properties = declaration["parameters"].get("properties", {})
        assert "patient_id" not in properties
        assert "phone" not in properties
