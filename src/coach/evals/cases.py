"""Synthetic training logs with planted stories.

Every case is thirteen ISO weeks of three sessions a week, built from a seed, and
emitted in Hevy's own JSON shape so it travels the same path as real data: raw
page, raw model, internal model, figures. The last week is the review week.

Stories are planted by editing one lift's load or RPE in the last weeks, so the
rest of the log stays a plausible, steadily progressing programme. The planted
numbers are chosen so each story is unambiguous in the figures; the test module
``tests/test_planted_stories.py`` is the written-down definition of "unambiguous".
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from coach.hevy.models import WorkoutsPage
from coach.model import MELBOURNE, WeekId, Workout, from_raw_pages

REVIEW_WEEK = WeekId(2026, 40)
WEEKS = 13
PAGE_SIZE = 10

SQUAT = ("Squat (Barbell)", "TPL00001", 100.0)
BENCH = ("Bench Press (Barbell)", "TPL00002", 70.0)
DEADLIFT = ("Deadlift (Barbell)", "TPL00003", 130.0)
OHP = ("Overhead Press (Barbell)", "TPL00004", 45.0)
PULLDOWN = ("Lat Pulldown (Cable)", "TPL00005", 50.0)
ROW = ("Dumbbell Row", "TPL00006", 25.0)
ACCESSORIES = {PULLDOWN[1], ROW[1]}

#: Monday, Wednesday, Friday.
SCHEDULE = (
    (0, "Lower A", (SQUAT, BENCH, PULLDOWN)),
    (2, "Pull", (DEADLIFT, OHP, ROW)),
    (4, "Lower B", (SQUAT, BENCH, PULLDOWN)),
)
NORMAL_RPE = (8.0, 8.5, 9.0)


class Story(StrEnum):
    """What the review is expected to find."""

    STEADY_PROGRESS = "steady_progress"
    BENCH_STALL = "bench_stall"
    SQUAT_PR = "squat_pr"
    RISING_RPE = "rising_rpe"
    MISSED_SESSIONS = "missed_sessions"
    DEADLIFT_REGRESSION = "deadlift_regression"
    COMBINED = "combined"
    NEGATIVE_QUIET = "negative_quiet"
    NEGATIVE_DELOAD = "negative_deload"


@dataclass(frozen=True)
class Expectation:
    """Where a story must appear: a review section and an exercise name, "Overall", or "any"."""

    section: str
    exercise: str


@dataclass(frozen=True)
class Case:
    """One eval case: a story, a seed, and what a correct review contains."""

    name: str
    story: Story
    seed: int
    expected: tuple[Expectation, ...]

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class BuiltCase:
    """A case rendered to data."""

    case: Case
    pages: list[WorkoutsPage]
    workouts: list[Workout]
    review_week: WeekId


_EXPECTED: dict[Story, tuple[Expectation, ...]] = {
    Story.STEADY_PROGRESS: (Expectation("highlights", "any"),),
    Story.BENCH_STALL: (Expectation("concerns", BENCH[0]),),
    Story.SQUAT_PR: (Expectation("highlights", SQUAT[0]),),
    Story.RISING_RPE: (Expectation("concerns", DEADLIFT[0]),),
    Story.MISSED_SESSIONS: (Expectation("concerns", "Overall"),),
    Story.DEADLIFT_REGRESSION: (Expectation("concerns", DEADLIFT[0]),),
    Story.COMBINED: (
        Expectation("concerns", BENCH[0]),
        Expectation("highlights", SQUAT[0]),
        Expectation("concerns", "Overall"),
    ),
    Story.NEGATIVE_QUIET: (),
    Story.NEGATIVE_DELOAD: (),
}


def _cases() -> list[Case]:
    cases = []
    for story in Story:
        seeds = (
            (1,)
            if story in (Story.COMBINED, Story.NEGATIVE_QUIET, Story.NEGATIVE_DELOAD)
            else (1, 2)
        )
        for n in seeds:
            cases.append(
                Case(
                    f"{story.value}-{n}",
                    story,
                    1000 * list(Story).index(story) + n,
                    _EXPECTED[story],
                )
            )
    return cases


CASES: list[Case] = _cases()


def _steady(base: float, week: int, step_every: int = 2) -> float:
    return base + 2.5 * (week // step_every)


def _half_kg(value: float) -> float:
    return round(value * 2) / 2


def _load_and_rpe(
    story: Story, template_id: str, base: float, week: int
) -> tuple[float, tuple[float, ...]]:
    """The top load and the three working-set RPEs for one lift in one week."""
    load = _steady(base, week, step_every=3 if story is Story.NEGATIVE_QUIET else 2)
    rpe = NORMAL_RPE
    stall = story in (Story.BENCH_STALL, Story.COMBINED) and template_id == BENCH[1] and week >= 8
    if stall:
        load = _steady(base, 8)
    if story in (Story.SQUAT_PR, Story.COMBINED) and template_id == SQUAT[1] and week == WEEKS - 1:
        load += 5.0
    if story is Story.RISING_RPE and template_id == DEADLIFT[1] and week >= 9:
        load = _steady(base, 9)
        rpe = ((6.5, 7.0, 7.5), (7.5, 8.0, 8.5), (8.5, 9.0, 9.5), (9.0, 9.5, 10.0))[week - 9]
    if story is Story.DEADLIFT_REGRESSION and template_id == DEADLIFT[1] and week >= 9:
        load = _half_kg(_steady(base, 9) * (1 - 0.025 * (week - 9)))
    if story is Story.NEGATIVE_DELOAD and week == WEEKS - 1:
        load = _half_kg(load * 0.85)
        rpe = (6.0, 6.5, 7.0)
    return load, rpe


def _sets(load: float, rpe: tuple[float, ...], reps: int = 5) -> list[dict]:
    sets = [
        {"index": 0, "type": "warmup", "weight_kg": _half_kg(load * 0.5), "reps": 8, "rpe": None},
        {"index": 1, "type": "warmup", "weight_kg": _half_kg(load * 0.75), "reps": 5, "rpe": None},
    ]
    for i, value in enumerate(rpe):
        sets.append(
            {"index": i + 2, "type": "normal", "weight_kg": load, "reps": reps, "rpe": value}
        )
    for s in sets:
        s.update({"distance_meters": None, "duration_seconds": None, "custom_metric": None})
    return sets


def raw_workouts(case: Case) -> list[dict]:
    """The case as Hevy-shaped workout dicts, oldest first."""
    rng = random.Random(case.seed)
    # Seeds vary the session minute and give each accessory one fixed load offset for the whole
    # case. A per-week accessory wobble would plant accidental stories in the negatives.
    accessory_offset = {
        template_id: rng.choice((-2.5, 0.0, 2.5)) for template_id in sorted(ACCESSORIES)
    }
    first_monday = REVIEW_WEEK.shift(-(WEEKS - 1)).monday()
    workouts = []
    for week in range(WEEKS):
        for offset, title, lifts in SCHEDULE:
            if (
                case.story in (Story.MISSED_SESSIONS, Story.COMBINED)
                and week == WEEKS - 1
                and offset != 0
            ):
                continue
            local = datetime.combine(
                first_monday + timedelta(weeks=week, days=offset), datetime.min.time()
            )
            local = local.replace(hour=7, minute=rng.randint(0, 45), tzinfo=MELBOURNE)
            exercises = []
            for index, (name, template_id, base) in enumerate(lifts):
                load, rpe = _load_and_rpe(case.story, template_id, base, week)
                if template_id in ACCESSORIES:
                    load += accessory_offset[template_id]
                exercises.append(
                    {
                        "index": index,
                        "title": name,
                        "notes": "",
                        "exercise_template_id": template_id,
                        "superset_id": None,
                        "sets": _sets(load, rpe),
                    }
                )
            full_title = (
                "Deload " if case.story is Story.NEGATIVE_DELOAD and week == WEEKS - 1 else ""
            ) + title
            stamp = _utc(local)
            end = _utc(local + timedelta(minutes=65))
            workouts.append(
                {
                    "id": f"{case.name}-{week:02d}-{offset}",
                    "title": full_title,
                    "routine_id": None,
                    "description": "",
                    "start_time": stamp,
                    "end_time": end,
                    "updated_at": end,
                    "created_at": end,
                    "exercises": exercises,
                }
            )
    return workouts


def _utc(local: datetime) -> str:
    """Render as Hevy does: UTC with an explicit +00:00 offset."""
    return local.astimezone(UTC).isoformat()


def raw_pages(case: Case) -> list[dict]:
    """The case as Hevy ``GET /v1/workouts`` page bodies, ten workouts per page."""
    workouts = raw_workouts(case)
    chunks = [workouts[i : i + PAGE_SIZE] for i in range(0, len(workouts), PAGE_SIZE)]
    return [
        {"page": n, "page_count": len(chunks), "workouts": chunk}
        for n, chunk in enumerate(chunks, start=1)
    ]


def build_case(case: Case) -> BuiltCase:
    """Render the case through the raw models into the internal model."""
    pages = [WorkoutsPage.model_validate(body) for body in raw_pages(case)]
    return BuiltCase(
        case=case, pages=pages, workouts=from_raw_pages(pages), review_week=REVIEW_WEEK
    )
