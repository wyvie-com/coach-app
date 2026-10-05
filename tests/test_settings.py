"""Credentials are read in one module, never printed, and errors name the variable."""

import pytest

from coach import settings
from coach.settings import MissingCredentialError, Secret


def test_secret_repr_and_str_are_redacted() -> None:
    secret = Secret("sk-ant-very-secret")
    assert "very-secret" not in repr(secret)
    assert "very-secret" not in str(secret)
    assert "very-secret" not in f"{secret}"
    assert secret.reveal() == "sk-ant-very-secret"


def test_anthropic_key_prefers_coach_variable() -> None:
    env = {"COACH_ANTHROPIC_API_KEY": "coach-key", "ANTHROPIC_API_KEY": "generic-key"}
    assert settings.anthropic_api_key(env).reveal() == "coach-key"


def test_anthropic_key_falls_back_to_generic_variable() -> None:
    env = {"ANTHROPIC_API_KEY": "generic-key"}
    assert settings.anthropic_api_key(env).reveal() == "generic-key"


def test_anthropic_key_missing_names_the_variable() -> None:
    with pytest.raises(MissingCredentialError) as excinfo:
        settings.anthropic_api_key({})
    message = str(excinfo.value)
    assert "COACH_ANTHROPIC_API_KEY" in message
    assert "ANTHROPIC_API_KEY" in message


def test_anthropic_key_blank_counts_as_missing() -> None:
    with pytest.raises(MissingCredentialError):
        settings.anthropic_api_key({"COACH_ANTHROPIC_API_KEY": "   "})


def test_hevy_env_route_when_key_is_set() -> None:
    credential = settings.hevy_credential({"HEVY_API_KEY": "hevy-key"})
    assert credential.route == "env"
    assert credential.header_value.reveal() == "hevy-key"


def test_hevy_proxy_route_sends_placeholder_when_key_is_unset() -> None:
    credential = settings.hevy_credential({})
    assert credential.route == "proxy"
    assert credential.header_value.reveal() == settings.PROXY_PLACEHOLDER
    assert settings.PROXY_PLACEHOLDER == "proxy-injected"


def test_review_model_default_and_override() -> None:
    assert settings.review_model({}) == settings.DEFAULT_MODEL
    assert settings.review_model({"COACH_MODEL": "claude-sonnet-5-5"}) == "claude-sonnet-5-5"
