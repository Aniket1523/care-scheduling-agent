"""Google Gemini client (google-genai SDK), the only provider (ADR-006).

Tools are passed as function declarations (JSON schemas), never as Python
callables, and automatic function calling is disabled: the SDK only reports
which tool the model wants; ``Agent`` decides whether and how to run it.
"""

from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

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
            # Retry rate limits and transient server errors (an eval run makes many
            # calls in a row). generate_content has no side effects, so this is safe.
            retry_options=types.HttpRetryOptions(attempts=4),
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
