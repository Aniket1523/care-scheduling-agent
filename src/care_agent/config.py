"""LLM configuration, read directly from environment variables (ADR-005).

Nothing here talks to a provider. Loading never fails just because the
configuration is incomplete: unit tests and the mock EHR need no API key.
Code that is about to build an LLM client calls ``require_complete()``,
which fails fast with the names of the missing variables.

The API key is held as a ``SecretStr`` so it never appears in ``repr``,
``str`` or serialised output.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

ENV_PROVIDER = "LLM_PROVIDER"
ENV_MODEL = "LLM_MODEL"
ENV_API_KEY = "LLM_API_KEY"
ENV_BASE_URL = "LLM_BASE_URL"
ENV_TIMEOUT_SECONDS = "LLM_TIMEOUT_SECONDS"
ENV_TEMPERATURE = "LLM_TEMPERATURE"

# Maps each environment variable to the settings field it populates.
_ENV_TO_FIELD = {
    ENV_PROVIDER: "provider",
    ENV_MODEL: "model",
    ENV_API_KEY: "api_key",
    ENV_BASE_URL: "base_url",
    ENV_TIMEOUT_SECONDS: "timeout_seconds",
    ENV_TEMPERATURE: "temperature",
}
_FIELD_TO_ENV = {field: env for env, field in _ENV_TO_FIELD.items()}

# Variables that must be set before an LLM client can be built.
_REQUIRED_FOR_CLIENT = (ENV_PROVIDER, ENV_MODEL, ENV_API_KEY)


class ConfigError(Exception):
    """Configuration is invalid or incomplete. Messages name variables, never values."""


class LLMSettings(BaseModel):
    # hide_input_in_errors: Pydantic validation errors (construction or assignment)
    # must never echo the offending value, which could be a secret.
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    provider: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)
    temperature: float = Field(default=0.0, ge=0, le=2)

    def __setattr__(self, name: str, value: object) -> None:
        # The model is immutable. Pydantic's own frozen-instance error ignores
        # hide_input_in_errors and would echo `value` (pydantic 2.14), so raise a
        # plain error that never includes the attempted value.
        raise TypeError("LLMSettings is immutable")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LLMSettings:
        """Build settings from ``environ`` (defaults to ``os.environ``).

        Unset and blank variables are treated the same: the field keeps its default.
        """
        source = os.environ if environ is None else environ
        values = {
            field: source[env].strip()
            for env, field in _ENV_TO_FIELD.items()
            if source.get(env, "").strip()
        }
        try:
            return cls(**values)
        except ValidationError as exc:
            # Report variable names and the reason only, never input values.
            problems = "; ".join(
                f"{_FIELD_TO_ENV.get(str(err['loc'][0]), err['loc'][0])}: {err['msg']}"
                for err in exc.errors(include_input=False)
            )
        # Raised outside the except block on purpose: raising inside it would keep
        # the ValidationError (and its raw inputs) reachable as __context__, even
        # with "from None", for any tool that walks the exception chain.
        raise ConfigError(f"Invalid LLM configuration: {problems}")

    def missing_for_client(self) -> list[str]:
        """Names of required variables that are not set."""
        return [env for env in _REQUIRED_FOR_CLIENT if getattr(self, _ENV_TO_FIELD[env]) is None]

    def require_complete(self) -> None:
        """Raise ``ConfigError`` if an LLM client cannot be built from these settings."""
        missing = self.missing_for_client()
        if missing:
            raise ConfigError(
                "Missing LLM configuration. Set these environment variables: " + ", ".join(missing)
            )
