"""The conversation loop.

One ``respond()`` call handles one caller message:

1. Append the caller's text to the history and ask the model what to do.
2. If the model requests tools, run them in Python (manual dispatch: the SDK
   never executes anything) and send the results back. Repeat, at most
   ``MAX_MODEL_CALLS`` times per caller message.
3. The turn ends when the model calls ``reply_to_patient`` and the claim guard
   accepts it, or answers in plain text that the guard accepts.
4. If the guard rejects the reply twice, the model fails, or the step limit is
   reached, the caller gets a deterministic reply built from the ledger.

History uses google-genai ``types.Content`` directly; the model's own content
objects are appended unchanged so provider metadata (e.g. thought signatures)
is preserved.
"""

from __future__ import annotations

from typing import Any, Protocol

from google.genai import types

from care_agent.agent import debug
from care_agent.agent.guard import check_reply, fallback_reply
from care_agent.agent.state import ConversationState
from care_agent.agent.tools import ToolRunner

MAX_MODEL_CALLS = 8
MAX_REJECTED_REPLIES = 2


class ModelClient(Protocol):
    """Anything that turns a conversation history into the model's next content.

    ``GeminiClient`` talks to the API; tests use a scripted fake.
    """

    def generate(self, contents: list[types.Content]) -> types.Content: ...


class Agent:
    def __init__(self, client: ModelClient, tools: ToolRunner, state: ConversationState) -> None:
        self.client = client
        self.tools = tools
        self.state = state
        self.history: list[types.Content] = []
        # The last exception raised by the model client, for the CLI to report.
        self.last_model_error: Exception | None = None

    def respond(self, caller_text: str) -> str:
        turn_start = len(self.history)
        self.tools.turn_actions = []
        self.history.append(_text_content("user", caller_text))
        rejected = 0
        for _ in range(MAX_MODEL_CALLS):
            try:
                content = self.client.generate(self.history)
            except Exception as exc:  # network, quota, bad model name, malformed response
                # Keep what the EHR shows; drop the half-finished exchange.
                self.last_model_error = exc
                del self.history[turn_start:]
                self.history.append(_text_content("user", caller_text))
                break
            self.history.append(content)
            parts = content.parts or []
            calls = [p.function_call for p in parts if p.function_call is not None]
            debug.log(
                "model.output",
                kind="tool_calls" if calls else "text",
                tools=[c.name for c in calls],
            )

            if not calls:
                text = "".join(p.text for p in parts if p.text and not p.thought).strip()
                decision = check_reply(text, [], self.state.ledger)
                final = decision.text if decision.ok and text else self._fallback()
                self.history[-1] = _text_content("model", final)
                return final

            responses = []
            final = None
            for call in calls:
                args = dict(call.args or {})
                debug.log("model.tool_call", tool=call.name, args=args)
                if call.name == "reply_to_patient":
                    decision = check_reply(
                        str(args.get("message", "")),
                        [str(a) for a in args.get("confirmed_action_ids") or []],
                        self.state.ledger,
                    )
                    if decision.ok and final is None:
                        final = decision.text
                        result: dict[str, Any] = {"status": "delivered"}
                    else:
                        rejected += 1
                        result = {
                            "status": "rejected",
                            "problems": list(decision.problems) or ["only one reply per turn"],
                            "verified_actions": {
                                e.action_id: e.summary for e in self.state.ledger.verified()
                            },
                        }
                    debug.log(
                        "claim_guard", status=result["status"], problems=result.get("problems")
                    )
                else:
                    result = self.tools.execute(call.name or "", args)
                responses.append(_function_response(call, result))
            self.history.append(types.Content(role="user", parts=responses))

            if final is not None:
                self.history.append(_text_content("model", final))
                return final
            if rejected >= MAX_REJECTED_REPLIES:
                break

        final = self._fallback()
        self.history.append(_text_content("model", final))
        return final

    def _fallback(self) -> str:
        return fallback_reply(self.state.ledger, self.tools.turn_actions)


def _text_content(role: str, text: str) -> types.Content:
    return types.Content(role=role, parts=[types.Part(text=text)])


def _function_response(call: types.FunctionCall, result: dict[str, Any]) -> types.Part:
    return types.Part(
        function_response=types.FunctionResponse(id=call.id, name=call.name, response=result)
    )
