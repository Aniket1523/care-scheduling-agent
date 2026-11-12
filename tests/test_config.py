"""Tests for LLM configuration loaded from environment variables."""

import logging
import traceback

import pytest
from pydantic import ValidationError

from care_agent.config import ConfigError, LLMSettings

SECRET = "sk-test-DO-NOT-LEAK-123"

FULL_ENV = {
    "LLM_PROVIDER": "example-provider",
    "LLM_MODEL": "example-model",
    "LLM_API_KEY": SECRET,
    "LLM_BASE_URL": "https://llm.example.test/v1",
    "LLM_TIMEOUT_SECONDS": "12.5",
    "LLM_TEMPERATURE": "0.3",
}


def test_empty_environment_uses_defaults():
    settings = LLMSettings.from_env({})
    assert settings.provider is None
    assert settings.model is None
    assert settings.api_key is None
    assert settings.base_url is None
    assert settings.timeout_seconds == 30.0
    assert settings.temperature == 0.0


def test_full_environment_is_parsed():
    settings = LLMSettings.from_env(FULL_ENV)
    assert settings.provider == "example-provider"
    assert settings.model == "example-model"
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == SECRET
    assert settings.base_url == "https://llm.example.test/v1"
    assert settings.timeout_seconds == 12.5
    assert settings.temperature == 0.3


def test_blank_values_are_treated_as_unset():
    settings = LLMSettings.from_env({"LLM_MODEL": "   ", "LLM_TIMEOUT_SECONDS": ""})
    assert settings.model is None
    assert settings.timeout_seconds == 30.0


def test_values_are_stripped():
    settings = LLMSettings.from_env({"LLM_MODEL": "  example-model  "})
    assert settings.model == "example-model"


def test_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from-os-environ")
    assert LLMSettings.from_env().model == "from-os-environ"


def test_incomplete_config_loads_but_cannot_build_a_client():
    settings = LLMSettings.from_env({"LLM_MODEL": "example-model"})
    assert settings.missing_for_client() == ["LLM_PROVIDER", "LLM_API_KEY"]
    with pytest.raises(ConfigError) as exc_info:
        settings.require_complete()
    message = str(exc_info.value)
    assert "LLM_PROVIDER" in message
    assert "LLM_API_KEY" in message
    assert "LLM_MODEL" not in message


def test_complete_config_passes_requirement_check():
    LLMSettings.from_env(FULL_ENV).require_complete()


def test_api_key_never_appears_in_text_output():
    settings = LLMSettings.from_env(FULL_ENV)
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
    assert SECRET not in settings.model_dump_json()
    assert SECRET not in str(settings.model_dump())


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("LLM_TIMEOUT_SECONDS", "not-a-number"),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_TIMEOUT_SECONDS", "-5"),
        ("LLM_TEMPERATURE", "2.5"),
        ("LLM_TEMPERATURE", "-0.1"),
    ],
)
def test_invalid_numeric_values_raise_config_error_naming_the_variable(variable, value):
    with pytest.raises(ConfigError) as exc_info:
        LLMSettings.from_env({variable: value})
    assert variable in str(exc_info.value)


def test_validation_error_does_not_echo_values():
    # A secret-looking value placed in a numeric field must not be echoed back.
    with pytest.raises(ConfigError) as exc_info:
        LLMSettings.from_env({"LLM_TEMPERATURE": SECRET})
    assert SECRET not in str(exc_info.value)


def test_config_error_does_not_retain_the_pydantic_error():
    # The original ValidationError holds the raw inputs. It must not be reachable
    # through the exception chain, printed or not.
    with pytest.raises(ConfigError) as exc_info:
        LLMSettings.from_env({"LLM_API_KEY": SECRET, "LLM_TEMPERATURE": SECRET})
    error = exc_info.value
    assert error.__context__ is None
    assert error.__cause__ is None
    assert SECRET not in "".join(traceback.format_exception(error))


def test_direct_construction_error_does_not_echo_input():
    with pytest.raises(ValidationError) as exc_info:
        LLMSettings(api_key=SECRET, temperature=SECRET)
    assert SECRET not in str(exc_info.value)
    assert SECRET not in repr(exc_info.value)


def test_assignment_raises_type_error_without_exposing_keys():
    new_secret = "sk-test-ASSIGNED-ALSO-SECRET-456"
    settings = LLMSettings.from_env(FULL_ENV)
    with pytest.raises(TypeError) as exc_info:
        settings.api_key = new_secret  # type: ignore[misc,assignment]
    error = exc_info.value
    rendered = str(error) + repr(error) + "".join(traceback.format_exception(error))
    assert new_secret not in rendered
    assert SECRET not in rendered
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == SECRET


def test_api_key_never_appears_in_logs(caplog):
    logger = logging.getLogger("care_agent.test")
    settings = LLMSettings.from_env(FULL_ENV)
    with caplog.at_level(logging.DEBUG, logger="care_agent.test"):
        logger.info("settings=%s", settings)
        logger.info("settings=%r", settings)
        logger.info("fields=%s", settings.__dict__)
        try:
            LLMSettings.from_env({"LLM_API_KEY": SECRET, "LLM_TEMPERATURE": SECRET})
        except ConfigError:
            logger.exception("config failed")
    assert "config failed" in caplog.text  # the exception record was actually captured
    assert SECRET not in caplog.text


def test_settings_are_immutable():
    settings = LLMSettings.from_env(FULL_ENV)
    with pytest.raises(TypeError):
        settings.model = "other"  # type: ignore[misc]
    assert settings.model == "example-model"
