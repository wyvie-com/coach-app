"""A read-only client for the Hevy public API.

Rate limits: the Hevy OpenAPI document (read 2026-10-05) documents no rate limit,
no 429 response and no Retry-After header. Its only guidance is not to schedule
requests exactly on the hour. So this client keeps a polite fixed interval between
pages, honours a Retry-After header if one ever arrives, and otherwise backs off
exponentially on 429 and 5xx for a bounded number of attempts.

Authentication: 401 is not documented by Hevy either. The client treats it as
"credential rejected" and names the delivery route in the error, because on the
proxy route a 401 means the platform proxy did not inject the header, which is a
configuration problem rather than a wrong key.

The client never logs or stores the header value. Only ``route`` is recorded.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from coach.hevy.models import WorkoutCount, WorkoutsPage
from coach.settings import HevyCredential, HevyRoute

BASE_URL = "https://api.hevyapp.com"
#: The documented maximum for GET /v1/workouts (Hevy OpenAPI: "Max 10").
MAX_WORKOUTS_PAGE_SIZE = 10
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 60.0
MAX_BACKOFF_SECONDS = 30.0


class HevyError(RuntimeError):
    """Hevy returned something the client cannot use. The message never includes a body."""


class HevyAuthError(HevyError):
    """Hevy returned 401. The message says which credential route was active and what that means."""


@dataclass(frozen=True)
class FetchedPage:
    """A validated page together with the body exactly as Hevy sent it, for verbatim storage."""

    page: WorkoutsPage
    raw: dict[str, Any]


class HevyClient:
    """Paged, retrying, read-only access to Hevy.

    Args:
        credential: which route and which header value to send; the value is never stored
            anywhere but the underlying ``httpx`` client's headers.
        transport: an ``httpx`` transport, so tests can script responses; None in production.
        timeout: per-request timeout in seconds.
        page_size: items per page, capped at the documented maximum of 10.
        interval: seconds to wait between consecutive page requests.
        max_attempts: total attempts per request, including the first.
        sleep: the sleep function, injectable so tests run without waiting.
    """

    def __init__(
        self,
        credential: HevyCredential,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        page_size: int = MAX_WORKOUTS_PAGE_SIZE,
        interval: float = 0.5,
        max_attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 1 <= page_size <= MAX_WORKOUTS_PAGE_SIZE:
            raise ValueError(f"page_size must be 1..{MAX_WORKOUTS_PAGE_SIZE}, got {page_size}")
        self.route: HevyRoute = credential.route
        self.page_size = page_size
        self._interval = interval
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"api-key": credential.header_value.reveal()},
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"HevyClient(route={self.route!r}, page_size={self.page_size})"

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def workout_count(self) -> int:
        """Return the total number of workouts on the account."""
        return self._parse(WorkoutCount, self._json(self._get("/v1/workouts/count"))).workout_count

    def iter_workout_pages(self) -> Iterator[FetchedPage]:
        """Yield every page of workouts, in page order, pausing ``interval`` seconds between pages.

        Stops when ``page == page_count`` as reported by the first page. Hevy does not
        document the order of workouts within or across pages, so callers sort by
        ``start_time`` themselves.
        """
        page_count: int | None = None
        number = 1
        while page_count is None or number <= page_count:
            if number > 1:
                self._sleep(self._interval)
            response = self._get(
                "/v1/workouts", params={"page": number, "pageSize": self.page_size}
            )
            raw = self._json(response)
            page = self._parse(WorkoutsPage, raw)
            if page.page != number:
                raise HevyError(f"Hevy returned page {page.page} when page {number} was requested")
            if page_count is None:
                page_count = page.page_count
            yield FetchedPage(page=page, raw=raw)
            number += 1

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise HevyError("Hevy response was not valid JSON") from exc

    @staticmethod
    def _parse[T](model: type[T], body: Any) -> T:
        try:
            return model.model_validate(body)  # type: ignore[attr-defined]
        except ValidationError as exc:
            raise HevyError(f"Hevy response did not match the expected shape: {exc}") from exc

    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        last = self._max_attempts - 1
        for attempt in range(self._max_attempts):
            try:
                response = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == last:
                    raise HevyError(
                        f"GET {path} failed after {self._max_attempts} attempts: "
                        f"{type(exc).__name__}"
                    ) from exc
                self._sleep(self._backoff(attempt))
                continue
            status = response.status_code
            if status == 200:
                return response
            if status == 401:
                raise HevyAuthError(self._auth_message())
            if status in RETRY_STATUSES and attempt < last:
                self._sleep(self._retry_delay(response, attempt))
                continue
            raise HevyError(f"Hevy returned {status} for GET {path}")
        raise AssertionError("unreachable")  # pragma: no cover

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After")
        if header is not None:
            try:
                return min(float(header), MAX_RETRY_AFTER_SECONDS)
            except ValueError:
                pass  # an HTTP-date form is possible in theory; fall back to backoff
        return self._backoff(attempt)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(float(2**attempt), MAX_BACKOFF_SECONDS)

    def _auth_message(self) -> str:
        if self.route == "proxy":
            return (
                "Hevy returned 401 (route=proxy): no HEVY_API_KEY is set, the placeholder header "
                "was sent, and the platform proxy is not injecting the real api-key header for "
                "this session."
            )
        return "Hevy returned 401 (route=env): Hevy rejected the value of HEVY_API_KEY."
