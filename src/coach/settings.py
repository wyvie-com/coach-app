"""Read credentials and configuration from the environment, in one place.

Why one module: every other module receives a ``Secret`` and never touches
``os.environ``, so a stray ``print`` or log line elsewhere cannot leak a key.
``Secret`` redacts itself in ``repr`` and ``str``; the raw value is only
reachable through ``reveal()``, which is easy to grep for in review.

The functions take an optional ``env`` mapping so tests never touch the real
environment and never need a key.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

#: The review model. Pinned snapshot id rather than the alias so that pricing
#: and the findings log always refer to one fixed model. Cited in docs/spec.md
#: section 4 (models overview, read 2026-10-05).
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

#: Sent in the Hevy ``api-key`` header when no key is configured. The platform
#: proxy replaces it after the request leaves the session; Hevy never sees it.
PROXY_PLACEHOLDER = "proxy-injected"

HevyRoute = Literal["env", "proxy"]


class MissingCredentialError(RuntimeError):
    """A required credential is absent. The message names the variable to set."""


class Secret:
    """A string that refuses to print itself.

    Why a class and not ``str``: an f-string or a logger will happily format a
    plain string. Wrapping the value makes leaking it a deliberate act.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """Return the raw value. Call this only at the point of use."""
        return self._value

    def __repr__(self) -> str:
        return "Secret(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)


@dataclass(frozen=True)
class HevyCredential:
    """How the Hevy client authenticates.

    ``route`` is the only thing ever recorded or printed: ``env`` means
    ``HEVY_API_KEY`` was set and is sent; ``proxy`` means no key is configured,
    the placeholder is sent, and the platform proxy injects the real header.
    """

    route: HevyRoute
    header_value: Secret


def _get(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def anthropic_api_key(env: Mapping[str, str] | None = None) -> Secret:
    """Return the Anthropic key from ``COACH_ANTHROPIC_API_KEY``, else ``ANTHROPIC_API_KEY``.

    Raises ``MissingCredentialError`` naming both variables when neither is set.
    """
    env = os.environ if env is None else env
    for name in ("COACH_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
        value = _get(env, name)
        if value is not None:
            return Secret(value)
    raise MissingCredentialError(
        "No Anthropic API key found: set COACH_ANTHROPIC_API_KEY "
        "(or ANTHROPIC_API_KEY as a fallback)."
    )


def hevy_credential(env: Mapping[str, str] | None = None) -> HevyCredential:
    """Pick the Hevy route: the key from ``HEVY_API_KEY`` when set, else the proxy placeholder."""
    env = os.environ if env is None else env
    value = _get(env, "HEVY_API_KEY")
    if value is not None:
        return HevyCredential(route="env", header_value=Secret(value))
    return HevyCredential(route="proxy", header_value=Secret(PROXY_PLACEHOLDER))


def review_model(env: Mapping[str, str] | None = None) -> str:
    """Return the review model id from ``COACH_MODEL``, else the pinned default."""
    env = os.environ if env is None else env
    return _get(env, "COACH_MODEL") or DEFAULT_MODEL
