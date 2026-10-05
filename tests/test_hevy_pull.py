"""`coach pull` end to end against the scripted server: counts only, nothing else."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from coach.hevy.client import HevyClient
from coach.hevy.pull import format_summary, pull
from coach.hevy.store import PullStore
from coach.settings import HevyCredential, Secret

FIXTURES = Path(__file__).parent / "fixtures" / "hevy"


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/workouts/count":
        return httpx.Response(200, json=json.loads((FIXTURES / "workouts-count.json").read_text()))
    n = request.url.params["page"]
    return httpx.Response(200, json=json.loads((FIXTURES / f"workouts-page-{n}.json").read_text()))


def test_pull_writes_pages_and_reports_counts_only(tmp_path: Path) -> None:
    credential = HevyCredential(route="proxy", header_value=Secret("proxy-injected"))
    client = HevyClient(credential, transport=httpx.MockTransport(_handler), sleep=lambda s: None)
    store = PullStore(tmp_path)

    summary = pull(client, store, today=date(2026, 10, 5))

    assert summary.workout_count == 6
    assert summary.pages == 3
    assert summary.workouts == 6
    assert summary.route == "proxy"
    assert summary.directory == tmp_path / "2026-10-05"
    assert (summary.directory / "manifest.json").exists()

    text = format_summary(summary)
    assert "6" in text and "proxy" in text
    for forbidden in ("weight_kg", "Squat", "60.0", "reps"):
        assert forbidden not in text
