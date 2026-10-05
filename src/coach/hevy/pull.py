"""``coach pull``: fetch every workout page and store it. Prints counts, never set data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from coach.hevy.client import HevyClient
from coach.hevy.store import DOCS_DATE, Manifest, PullStore


@dataclass(frozen=True)
class PullSummary:
    """Everything ``coach pull`` is allowed to say about a pull."""

    directory: Path
    route: str
    workout_count: int
    pages: int
    workouts: int


def pull(client: HevyClient, store: PullStore, *, today: date) -> PullSummary:
    """Fetch the count, then every page, writing each page as it arrives."""
    run = store.begin(today)
    workout_count = client.workout_count()
    pages = 0
    workouts = 0
    for fetched in client.iter_workout_pages():
        # Store the body Hevy sent, not our parsed view of it, so nothing is lost.
        run.write_page(fetched.page, fetched.raw)
        pages += 1
        workouts += len(fetched.page.workouts)
    run.write_manifest(
        Manifest(
            pulled_on=today.isoformat(),
            route=client.route,
            docs_date=DOCS_DATE,
            page_size=client.page_size,
            pages=pages,
            workouts=workouts,
            workout_count=workout_count,
        )
    )
    return PullSummary(
        directory=run.directory,
        route=client.route,
        workout_count=workout_count,
        pages=pages,
        workouts=workouts,
    )


def format_summary(summary: PullSummary) -> str:
    """Render the summary as a few counts-only lines."""
    return "\n".join(
        [
            f"route           {summary.route}",
            f"workout_count   {summary.workout_count}",
            f"pages           {summary.pages}",
            f"workouts        {summary.workouts}",
            f"directory       {summary.directory}",
        ]
    )
