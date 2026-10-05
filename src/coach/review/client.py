"""The Anthropic client, built once with the key passed explicitly, behind a small protocol.

The protocol is the seam the tests use: a scripted fake with the same ``messages.create``
shape stands in for the SDK client, and the loop cannot tell the difference.
"""

from __future__ import annotations

from typing import Any, Protocol

import anthropic
from anthropic.types import Message

from coach.settings import Secret


class MessagesLike(Protocol):
    """The one method the loop calls."""

    def create(self, **kwargs: Any) -> Message:
        """Send one Messages API request."""
        ...


class ClaudeClient(Protocol):
    """What the loop needs from a client."""

    messages: MessagesLike


def build_client(key: Secret) -> anthropic.Anthropic:
    """The real client. Transport retries stay at the SDK default of two; content is never retried.

    Timeout is generous because a tool round trip is two requests and Haiku is fast anyway.
    """
    return anthropic.Anthropic(api_key=key.reveal(), max_retries=2, timeout=120.0)
