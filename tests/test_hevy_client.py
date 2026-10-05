"""The read-only Hevy client: pagination, retries, auth errors, polite interval."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from coach.hevy.client import HevyAuthError, HevyClient, HevyError
from coach.settings import HevyCredential, Secret

FIXTURES = Path(__file__).parent / "fixtures" / "hevy"
KEY = "11111111-2222-3333-4444-555555555555"


def _page(n: int) -> dict:
    return json.loads((FIXTURES / f"workouts-page-{n}.json").read_text())


class Script:
    """A scripted HTTP server: a queue of responses plus a log of requests and sleeps."""

    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def _client(script: Script, route: str = "env", **kwargs) -> HevyClient:
    value = KEY if route == "env" else "proxy-injected"
    credential = HevyCredential(route=route, header_value=Secret(value))
    return HevyClient(
        credential,
        transport=httpx.MockTransport(script.handler),
        sleep=script.sleep,
        **kwargs,
    )


def test_three_page_pagination_stops_at_page_count() -> None:
    script = Script([httpx.Response(200, json=_page(n)) for n in (1, 2, 3)])
    fetched = list(_client(script).iter_workout_pages())

    assert [f.page.page for f in fetched] == [1, 2, 3]
    assert sum(len(f.page.workouts) for f in fetched) == 6
    # The raw body is what Hevy sent, byte for byte after JSON decoding.
    assert fetched[1].raw == _page(2)
    assert [r.url.params["page"] for r in script.requests] == ["1", "2", "3"]
    assert {r.url.params["pageSize"] for r in script.requests} == {"10"}
    assert all(r.url.path == "/v1/workouts" for r in script.requests)
    assert all(r.headers["api-key"] == KEY for r in script.requests)
    # Polite interval between pages, not before the first one and not after the last.
    assert script.sleeps == [0.5, 0.5]


def test_page_number_mismatch_is_an_error() -> None:
    wrong = _page(1)
    wrong["page"] = 7
    script = Script([httpx.Response(200, json=wrong)])
    with pytest.raises(HevyError, match="page 7"):
        list(_client(script).iter_workout_pages())


def test_429_is_retried_and_retry_after_is_honoured() -> None:
    script = Script(
        [
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, json={"workout_count": 6}),
        ]
    )
    assert _client(script).workout_count() == 6
    assert len(script.requests) == 2
    assert script.sleeps == [3.0]


def test_5xx_is_retried_with_exponential_backoff() -> None:
    script = Script(
        [
            httpx.Response(503),
            httpx.Response(500),
            httpx.Response(200, json={"workout_count": 6}),
        ]
    )
    assert _client(script).workout_count() == 6
    assert script.sleeps == [1.0, 2.0]


def test_retries_are_bounded() -> None:
    script = Script([httpx.Response(503)] * 5)
    with pytest.raises(HevyError, match="503"):
        _client(script, max_attempts=5).workout_count()
    assert len(script.requests) == 5


def test_connection_errors_are_retried_then_raised() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    script = Script([])
    credential = HevyCredential(route="env", header_value=Secret(KEY))
    client = HevyClient(
        credential, transport=httpx.MockTransport(boom), sleep=script.sleep, max_attempts=3
    )
    with pytest.raises(HevyError, match="ConnectError"):
        client.workout_count()
    assert script.sleeps == [1.0, 2.0]


def test_401_on_env_route_blames_the_key_without_printing_it() -> None:
    script = Script([httpx.Response(401)])
    with pytest.raises(HevyAuthError) as excinfo:
        _client(script, route="env").workout_count()
    message = str(excinfo.value)
    assert "HEVY_API_KEY" in message and "route=env" in message
    assert KEY not in message


def test_401_on_proxy_route_blames_the_proxy() -> None:
    script = Script([httpx.Response(401)])
    with pytest.raises(HevyAuthError) as excinfo:
        _client(script, route="proxy").workout_count()
    message = str(excinfo.value)
    assert "proxy" in message and "api-key" in message and "route=proxy" in message
    assert script.requests[0].headers["api-key"] == "proxy-injected"


def test_401_is_never_retried() -> None:
    script = Script([httpx.Response(401), httpx.Response(200, json={"workout_count": 1})])
    with pytest.raises(HevyAuthError):
        _client(script).workout_count()
    assert len(script.requests) == 1


def test_other_4xx_is_an_error_without_the_body() -> None:
    script = Script([httpx.Response(400, json={"error": "Invalid page size", "secret": "nope"})])
    with pytest.raises(HevyError) as excinfo:
        _client(script).workout_count()
    assert "400" in str(excinfo.value)
    assert "nope" not in str(excinfo.value)


def test_malformed_page_is_rejected_as_hevy_error() -> None:
    bad = json.loads((FIXTURES / "malformed-missing-workouts.json").read_text())
    script = Script([httpx.Response(200, json=bad)])
    with pytest.raises(HevyError, match="workouts"):
        list(_client(script).iter_workout_pages())


def test_client_records_its_route() -> None:
    assert _client(Script([]), route="proxy").route == "proxy"
    assert _client(Script([]), route="env").route == "env"
    assert KEY not in repr(_client(Script([]), route="env"))
