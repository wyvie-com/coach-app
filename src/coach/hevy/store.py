"""Where raw Hevy pages live: ``<root>/<YYYY-MM-DD>/page-NNN.json`` plus ``manifest.json``.

The root is ``private/hevy/`` in normal use, which is gitignored. Pages are stored
verbatim so figures can be recomputed offline if Hevy changes or disappears. The
manifest holds counts, the route and the docs date, never set data and never a
header value. This is the only module that writes under ``private/``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from coach.hevy.models import WorkoutsPage

#: The Hevy OpenAPI document version these pages were validated against.
DOCS_DATE = "2026-10-05"


@dataclass(frozen=True)
class Manifest:
    """What a pull produced, in counts. Written beside the pages."""

    pulled_on: str
    route: str
    docs_date: str
    page_size: int
    pages: int
    workouts: int
    workout_count: int


@dataclass(frozen=True)
class PullRun:
    """One dated directory being written."""

    directory: Path

    def write_page(self, page: WorkoutsPage, raw: Any) -> Path:
        """Write the page body exactly as received, named by its page number."""
        path = self.directory / f"page-{page.page:03d}.json"
        path.write_text(json.dumps(raw, indent=2) + "\n")
        return path

    def write_manifest(self, manifest: Manifest) -> Path:
        """Write the counts manifest."""
        path = self.directory / "manifest.json"
        path.write_text(json.dumps(asdict(manifest), indent=2) + "\n")
        return path


class PullStore:
    """The dated directories under one root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def begin(self, day: date) -> PullRun:
        """Create (or reuse) the directory for ``day`` and return a handle for writing."""
        directory = self.root / day.isoformat()
        directory.mkdir(parents=True, exist_ok=True)
        return PullRun(directory)

    def latest(self) -> date | None:
        """Return the most recent pull date on disk, or None."""
        if not self.root.exists():
            return None
        days = []
        for child in self.root.iterdir():
            try:
                days.append(date.fromisoformat(child.name))
            except ValueError:
                continue
        return max(days, default=None)

    def read_pages(self, day: date) -> list[WorkoutsPage]:
        """Load and validate every page written on ``day``, in page order."""
        directory = self.root / day.isoformat()
        pages = [
            WorkoutsPage.model_validate(json.loads(path.read_text()))
            for path in sorted(directory.glob("page-*.json"))
        ]
        return sorted(pages, key=lambda p: p.page)
