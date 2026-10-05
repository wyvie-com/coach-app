"""The credential check reports status codes and routes, never key material."""

from __future__ import annotations

import httpx

from coach import credentials
from coach.settings import HevyCredential, Secret

HEVY_KEY = "11111111-2222-3333-4444-555555555555"


def _hevy_transport(expected_header: str, status: int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/workouts/count"
        assert request.headers["api-key"] == expected_header
        return httpx.Response(status, json={"workout_count": 3})

    return httpx.MockTransport(handler)


def test_hevy_env_route_sends_the_key_and_reports_status_only() -> None:
    credential = HevyCredential(route="env", header_value=Secret(HEVY_KEY))
    result = credentials.check_hevy(credential, transport=_hevy_transport(HEVY_KEY, 200))
    assert result.status == 200
    assert result.detail == "route=env"
    assert HEVY_KEY not in repr(result)


def test_hevy_proxy_route_sends_placeholder() -> None:
    credential = HevyCredential(route="proxy", header_value=Secret("proxy-injected"))
    result = credentials.check_hevy(credential, transport=_hevy_transport("proxy-injected", 200))
    assert result.status == 200
    assert result.detail == "route=proxy"


def test_hevy_401_in_proxy_mode_explains_the_proxy() -> None:
    credential = HevyCredential(route="proxy", header_value=Secret("proxy-injected"))
    result = credentials.check_hevy(credential, transport=_hevy_transport("proxy-injected", 401))
    assert result.status == 401
    assert "proxy" in result.detail
    assert "api-key" in result.detail


def test_hevy_401_in_env_mode_blames_the_key() -> None:
    credential = HevyCredential(route="env", header_value=Secret(HEVY_KEY))
    result = credentials.check_hevy(credential, transport=_hevy_transport(HEVY_KEY, 401))
    assert result.status == 401
    assert "HEVY_API_KEY" in result.detail
    assert HEVY_KEY not in result.detail


def test_hevy_connection_error_has_no_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    credential = HevyCredential(route="proxy", header_value=Secret("proxy-injected"))
    result = credentials.check_hevy(credential, transport=httpx.MockTransport(handler))
    assert result.status is None
    assert "ConnectError" in result.detail


class _RawModels:
    def __init__(self, outcome: int | Exception) -> None:
        self._outcome = outcome

    def list(self, *, limit: int) -> object:
        assert limit == 1
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return type("Raw", (), {"status_code": self._outcome})()


class _FakeAnthropic:
    def __init__(self, outcome: int | Exception) -> None:
        self.models = type("Models", (), {"with_raw_response": _RawModels(outcome)})()


def test_anthropic_success_reports_200() -> None:
    result = credentials.check_anthropic(_FakeAnthropic(200))
    assert result.status == 200
    assert result.detail == "GET /v1/models"


def test_anthropic_status_error_reports_its_code() -> None:
    import anthropic

    response = httpx.Response(
        401, request=httpx.Request("GET", "https://api.anthropic.com/v1/models")
    )
    error = anthropic.AuthenticationError("bad key", response=response, body=None)
    result = credentials.check_anthropic(_FakeAnthropic(error))
    assert result.status == 401
    assert "COACH_ANTHROPIC_API_KEY" in result.detail


def test_anthropic_connection_error_has_no_status() -> None:
    import anthropic

    request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
    result = credentials.check_anthropic(
        _FakeAnthropic(anthropic.APIConnectionError(request=request))
    )
    assert result.status is None
    assert "APIConnectionError" in result.detail


def test_render_table_never_mentions_a_value() -> None:
    rows = [
        credentials.CheckResult("anthropic", 200, "GET /v1/models"),
        credentials.CheckResult("hevy", 401, "route=proxy; the proxy is not injecting api-key"),
    ]
    text = credentials.render(rows)
    assert "anthropic" in text and "200" in text and "401" in text
    assert "sk-" not in text
