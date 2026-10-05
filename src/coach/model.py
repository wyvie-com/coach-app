"""The internal model: what the figures are computed from.

Why a second model after ``coach.hevy.models``: the raw models mirror Hevy and
tolerate anything; this one fixes the rules the figures depend on. A workout's
week is the ISO week of its start in Australia/Melbourne, set types collapse to
a closed enum, and supersets become a flag. Everything downstream reads this
model and never a Hevy dict.

Mapping rules (docs/spec.md section 2.2):

- Week: ``start_time`` converted to Melbourne, then ``date.isocalendar()``. The
  API has no time zone field, so the zone is a constant here, not data.
- Set kind: ``normal``, ``warmup``, ``dropset``, ``failure`` as Hevy names them;
  anything else is kept as ``OTHER`` with the original text preserved.
- Working set: every set that is not a warm-up. Drop sets and failure sets count.
- Notes and descriptions are not carried over. Titles are, because they are short
  labels and a title such as "Deload" is a legitimate signal.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from coach.hevy.models import RawExercise, RawSet, RawWorkout, WorkoutsPage

#: The one time zone this project uses. Configurable zones are in docs/later.md.
MELBOURNE = ZoneInfo("Australia/Melbourne")

_WEEK_RE = re.compile(r"(\d{4})-W(\d{2})")


@dataclass(frozen=True, order=True)
class WeekId:
    """An ISO week, written ``2026-W40``."""

    year: int
    week: int

    @classmethod
    def parse(cls, text: str) -> WeekId:
        """Parse ``YYYY-Www``; the week must exist in that ISO year."""
        match = _WEEK_RE.fullmatch(text.strip())
        if not match:
            raise ValueError(f"expected an ISO week like 2026-W40, got {text!r}")
        year, week = int(match.group(1)), int(match.group(2))
        date.fromisocalendar(year, week, 1)  # raises ValueError for week 0 or a missing week 53
        return cls(year, week)

    @classmethod
    def of_date(cls, day: date) -> WeekId:
        """The ISO week containing ``day``."""
        iso = day.isocalendar()
        return cls(iso.year, iso.week)

    def monday(self) -> date:
        """The Monday that starts this week."""
        return date.fromisocalendar(self.year, self.week, 1)

    def shift(self, weeks: int) -> WeekId:
        """The week ``weeks`` after this one (negative for earlier)."""
        return WeekId.of_date(self.monday() + timedelta(weeks=weeks))

    def __str__(self) -> str:
        return f"{self.year}-W{self.week:02d}"


class SetKind(StrEnum):
    """Hevy's four set types plus a bucket for anything the API adds later."""

    NORMAL = "normal"
    WARMUP = "warmup"
    DROPSET = "dropset"
    FAILURE = "failure"
    OTHER = "other"

    @classmethod
    def from_raw(cls, text: str) -> SetKind:
        """Map Hevy's text to a kind; unknown text becomes ``OTHER``."""
        try:
            return cls(text)
        except ValueError:
            return cls.OTHER


@dataclass(frozen=True)
class Set:
    """One set. ``raw_type`` keeps Hevy's text so an ``OTHER`` set can be explained."""

    index: int
    kind: SetKind
    raw_type: str
    weight_kg: float | None
    reps: int | None
    rpe: float | None

    @property
    def is_working(self) -> bool:
        """Every set that is not a warm-up counts towards the figures."""
        return self.kind is not SetKind.WARMUP


@dataclass(frozen=True)
class Exercise:
    """One exercise within a workout, keyed across weeks by ``template_id``."""

    template_id: str
    title: str
    superset: bool
    sets: tuple[Set, ...]


@dataclass(frozen=True)
class Workout:
    """One session. ``week`` and ``local_date`` derive from ``start`` in Melbourne time."""

    id: str
    title: str
    start: datetime
    end: datetime
    exercises: tuple[Exercise, ...]

    @property
    def local_date(self) -> date:
        """The calendar date of the start in Melbourne."""
        return self.start.astimezone(MELBOURNE).date()

    @property
    def week(self) -> WeekId:
        """The ISO week this workout belongs to."""
        return WeekId.of_date(self.local_date)


def _set(raw: RawSet) -> Set:
    return Set(
        index=raw.index,
        kind=SetKind.from_raw(raw.type),
        raw_type=raw.type,
        weight_kg=raw.weight_kg,
        reps=raw.reps,
        rpe=raw.rpe,
    )


def _exercise(raw: RawExercise) -> Exercise:
    return Exercise(
        template_id=raw.exercise_template_id,
        title=raw.title,
        superset=raw.superset_id is not None,
        sets=tuple(_set(s) for s in sorted(raw.sets, key=lambda s: s.index)),
    )


def from_raw_workout(raw: RawWorkout) -> Workout:
    """Convert one validated Hevy workout."""
    return Workout(
        id=raw.id,
        title=raw.title,
        start=raw.start_time,
        end=raw.end_time,
        exercises=tuple(_exercise(e) for e in sorted(raw.exercises, key=lambda e: e.index)),
    )


def from_raw_pages(pages: Iterable[WorkoutsPage]) -> list[Workout]:
    """Convert every page, drop duplicate ids (Hevy's page order is undocumented), sort by start."""
    seen: dict[str, Workout] = {}
    for page in pages:
        for raw in page.workouts:
            seen.setdefault(raw.id, from_raw_workout(raw))
    return sorted(seen.values(), key=lambda w: (w.start, w.id))
