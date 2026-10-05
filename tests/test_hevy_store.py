"""Raw pages land under private/hevy/<date>/ with a manifest of counts only."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from coach.hevy.models import WorkoutsPage
from coach.hevy.store import Manifest, PullStore


def test_store_writes_pages_and_manifest(tmp_path: Path, hevy_fixture) -> None:
    store = PullStore(tmp_path / "private" / "hevy")
    run = store.begin(date(2026, 10, 5))
    for n in (1, 2, 3):
        raw = hevy_fixture(f"workouts-page-{n}.json")
        run.write_page(WorkoutsPage.model_validate(raw), raw)
    manifest = Manifest(
        pulled_on="2026-10-05",
        route="proxy",
        docs_date="2026-10-05",
        page_size=10,
        pages=3,
        workouts=6,
        workout_count=6,
    )
    run.write_manifest(manifest)

    files = sorted(p.name for p in (tmp_path / "private" / "hevy" / "2026-10-05").iterdir())
    assert files == ["manifest.json", "page-001.json", "page-002.json", "page-003.json"]
    written = json.loads((run.directory / "page-002.json").read_text())
    assert written == hevy_fixture("workouts-page-2.json")
    stored = json.loads((run.directory / "manifest.json").read_text())
    assert stored["workouts"] == 6 and stored["route"] == "proxy"
    assert "weight_kg" not in json.dumps(stored)


def test_store_reads_pages_back_in_order(tmp_path: Path, hevy_fixture) -> None:
    store = PullStore(tmp_path)
    run = store.begin(date(2026, 10, 5))
    for n in (3, 1, 2):
        raw = hevy_fixture(f"workouts-page-{n}.json")
        run.write_page(WorkoutsPage.model_validate(raw), raw)
    pages = store.read_pages(date(2026, 10, 5))
    assert [p.page for p in pages] == [1, 2, 3]


def test_latest_pull_date(tmp_path: Path) -> None:
    store = PullStore(tmp_path)
    assert store.latest() is None
    store.begin(date(2026, 9, 28))
    store.begin(date(2026, 10, 5))
    assert store.latest() == date(2026, 10, 5)
