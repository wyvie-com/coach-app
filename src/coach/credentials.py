"""The slice 0 credential check: one request per service, reporting status codes only.

Why it exists: live runs happen in cloud sessions where the Hevy key may arrive
through a proxy rather than an environment variable. Before any model call we
want two numbers (HTTP statuses) and one word (which Hevy route was active),
and nothing that could identify the key or the account.

Sources (read 2026-10-05): ``GET /v1/models`` needs ``x-api-key`` and
``anthropic-version`` headers, which the SDK sets
(platform.claude.com/docs/en/api/models/list). ``GET /v1/workouts/count``
returns ``{"workout_count": n}`` and needs the ``api-key`` header (Hevy
OpenAPI document behind api.hevyapp.com/docs/).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import anthropic
import httpx

from coach.settings import HevyCredential, Secret

HEVY_BASE_URL = "https://api.hevyapp.com"
HEVY_COUNT_PATH = "/v1/workouts/count"


@dataclass(frozen=True)
class CheckResult:
    """One line of the credential report. ``status`` is None when no HTTP response arrived."""

    service: str
    status: int | None
    detail: str

    @property
    def ok(self) -> bool:
        """True only for an HTTP 200."""
        return self.status == 200


class _RawModelsLike(Protocol):
    def list(self, *, limit: int) -> Any: ...


class _ModelsLike(Protocol):
    with_raw_response: _RawModelsLike


class AnthropicLike(Protocol):
    """The slice of the Anthropic client this module uses, so tests can fake it."""

    models: _ModelsLike


def build_anthropic_client(key: Secret) -> anthropic.Anthropic:
    """Build the SDK client with the key passed explicitly, never read from the environment.

    ``max_retries=0`` because a credential check should report the first answer,
    not mask a 401 behind the SDK's default two retries.
    """
    return anthropic.Anthropic(api_key=key.reveal(), max_retries=0, timeout=30.0)


def check_anthropic(client: AnthropicLike) -> CheckResult:
    """List one model and report the HTTP status of that request."""
    try:
        raw = client.models.with_raw_response.list(limit=1)
    except anthropic.APIStatusError as exc:
        hint = " (COACH_ANTHROPIC_API_KEY rejected)" if exc.status_code == 401 else ""
        return CheckResult("anthropic", exc.status_code, f"GET /v1/models{hint}")
    except anthropic.APIConnectionError as exc:
        return CheckResult("anthropic", None, f"GET /v1/models failed: {type(exc).__name__}")
    return CheckResult("anthropic", raw.status_code, "GET /v1/models")


def check_hevy(
    credential: HevyCredential,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 10.0,
) -> CheckResult:
    """Fetch the workout count and report the HTTP status and the route, never the header value.

    ``transport`` lets tests substitute ``httpx.MockTransport``; production passes None.
    """
    headers = {"api-key": credential.header_value.reveal()}
    try:
        with httpx.Client(
            base_url=HEVY_BASE_URL, headers=headers, timeout=timeout, transport=transport
        ) as http:
            response = http.get(HEVY_COUNT_PATH)
    except httpx.HTTPError as exc:
        return CheckResult("hevy", None, f"route={credential.route}; {type(exc).__name__}")

    detail = f"route={credential.route}"
    if response.status_code == 401:
        if credential.route == "proxy":
            detail += (
                "; Hevy rejected the request and no HEVY_API_KEY is set, so the platform proxy "
                "is not injecting the api-key header for this session"
            )
        else:
            detail += "; Hevy rejected the value of HEVY_API_KEY"
    return CheckResult("hevy", response.status_code, detail)


def render(results: list[CheckResult]) -> str:
    """Format the report as fixed-width lines. Contains statuses and routes only."""
    width = max(len(r.service) for r in results)
    lines = []
    for r in results:
        status = "---" if r.status is None else str(r.status)
        lines.append(f"{r.service.ljust(width)}  {status:>3}  {r.detail}")
    return "\n".join(lines)
