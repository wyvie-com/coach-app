"""Shared test setup: no test may open a network socket.

Why: the brief says Hevy and Claude responses in tests come from fixtures. Making
``socket.getaddrinfo`` fail turns that rule into a test failure instead of a hope.
``httpx.MockTransport`` never resolves a host, so the mocked paths are unaffected.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("tests must not touch the network")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture
def hevy_fixture() -> callable:
    """Load a JSON fixture from tests/fixtures/hevy by file name."""

    def load(name: str) -> dict:
        return json.loads((FIXTURES / "hevy" / name).read_text())

    return load
