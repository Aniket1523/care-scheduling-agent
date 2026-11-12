"""A scripted stand-in for Gemini, so agent tests need no network or API key.

``ScriptedModel(steps)`` returns one step per ``generate()`` call. A step is a
``types.Content`` (the model's next message) or a function of the history
returning one, which lets a reply confirm the action ID a tool just returned.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import count
from typing import Any

from google.genai import types

Step = types.Content | Callable[[list[types.Content]], types.Content]
_call_ids = count(1)


class ScriptedModel:
    def __init__(self, steps: list[Step]) -> None:
        self.steps = list(steps)
        self.seen: list[list[types.Content]] = []  # history passed to each call
        self.over_called = False

    def generate(self, contents: list[types.Content]) -> types.Content:
        self.seen.append(list(contents))
        if not self.steps:
            self.over_called = True
            raise AssertionError("ScriptedModel has no steps left")
        step = self.steps.pop(0)
        return step(contents) if callable(step) else step

    def assert_finished(self) -> None:
        assert not self.over_called, "the agent asked the model for more steps than scripted"
        assert not self.steps, f"{len(self.steps)} scripted steps were never used"


def call(name: str, **args: Any) -> types.Content:
    """The model requests one tool call."""
    function_call = types.FunctionCall(id=f"call{next(_call_ids)}", name=name, args=args)
    return types.Content(role="model", parts=[types.Part(function_call=function_call)])


def say(text: str) -> types.Content:
    """The model answers in plain text (no tool call)."""
    return types.Content(role="model", parts=[types.Part(text=text)])


def reply(message: str, confirmed: list[str] | None = None) -> types.Content:
    return call("reply_to_patient", message=message, confirmed_action_ids=confirmed or [])


def last_results(contents: list[types.Content]) -> list[dict]:
    """Tool results the agent sent back in its most recent message."""
    parts = contents[-1].parts or []
    return [p.function_response.response for p in parts if p.function_response is not None]


def reply_confirming_last(message: str) -> Step:
    """Reply that confirms every verified action in the latest tool results."""

    def step(contents: list[types.Content]) -> types.Content:
        ids = [r["action_id"] for r in last_results(contents) if r.get("verified")]
        return reply(message, ids)

    return step


def reply_claiming_last_action(message: str) -> Step:
    """Reply that confirms the latest action ID whatever its result (a lying model)."""

    def step(contents: list[types.Content]) -> types.Content:
        ids = [r["action_id"] for r in last_results(contents) if r.get("action_id")]
        return reply(message, ids)

    return step
