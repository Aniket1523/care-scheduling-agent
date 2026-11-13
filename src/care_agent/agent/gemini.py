"""Google Gemini client (google-genai SDK), the only provider (ADR-006).

Tools are passed as function declarations (JSON schemas), never as Python
callables, and automatic function calling is disabled: the SDK only reports
which tool the model wants; ``Agent`` decides whether and how to run it.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import errors, types

from care_agent.config import LLMSettings


class GeminiClient:
    def __init__(
        self,
        settings: LLMSettings,
        system_prompt: str,
        tool_declarations: list[dict[str, Any]],
    ) -> None:
        settings.require_complete()  # raises ConfigError (no network involved)
        assert settings.api_key is not None
        http_options = types.HttpOptions(
            timeout=int(settings.timeout_seconds * 1000),
            base_url=settings.base_url,
            # Short SDK retries for timeouts and server errors. Rate limits (429) are
            # not retried here: RateLimitedClient waits much longer for them.
            # generate_content has no side effects, so retrying is safe.
            retry_options=types.HttpRetryOptions(
                attempts=4, http_status_codes=[408, 500, 502, 503, 504]
            ),
        )
        self._client = genai.Client(
            api_key=settings.api_key.get_secret_value(), http_options=http_options
        )
        self.model = settings.model
        self.config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=settings.temperature,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=d["name"],
                            description=d["description"],
                            parameters_json_schema=d["parameters"],
                        )
                        for d in tool_declarations
                    ]
                )
            ],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def generate(self, contents: list[types.Content]) -> types.Content:
        response = self._client.models.generate_content(
            model=self.model, contents=contents, config=self.config
        )
        if not response.candidates or response.candidates[0].content is None:
            raise RuntimeError("Gemini returned no content")
        return response.candidates[0].content


def is_rate_limit(exc: BaseException) -> bool:
    """A Gemini 429 / RESOURCE_EXHAUSTED (rate limit or quota)."""
    return isinstance(exc, errors.APIError) and (
        exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED"
    )


class RateLimitedClient:
    """Wraps a model client: spaces calls out and retries rate limits with backoff.

    A model call has no side effects, so repeating the same request is safe and
    does not change what the agent decides. Retry waits grow exponentially
    (``base_delay * 2**n``, capped at ``max_delay``) plus up to ``jitter`` seconds
    of random jitter. If every attempt is rate-limited, the last error is raised:
    the agent loop then reports a model error, which the evaluation grades as
    ``error`` (exit 2), never as a scenario failure or a regression.
    """

    def __init__(
        self,
        client: Any,
        *,
        min_interval: float = 0.0,
        max_attempts: int = 5,
        base_delay: float = 5.0,
        max_delay: float = 60.0,
        jitter: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self.client = client
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._sleep = sleep
        self._clock = clock
        self._rand = rand
        self._last_call: float | None = None

    def generate(self, contents: list[types.Content]) -> types.Content:
        for attempt in range(self.max_attempts):
            self._pace()
            try:
                return self.client.generate(contents)
            except Exception as exc:
                if not is_rate_limit(exc) or attempt == self.max_attempts - 1:
                    raise
                delay = min(self.max_delay, self.base_delay * 2**attempt)
                self._sleep(delay + self.jitter * self._rand())
        raise AssertionError("unreachable")  # the loop always returns or raises

    def _pace(self) -> None:
        now = self._clock()
        if self._last_call is not None and self.min_interval > 0:
            wait = self.min_interval - (now - self._last_call)
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last_call = now
