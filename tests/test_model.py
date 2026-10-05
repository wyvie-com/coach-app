"""Raw pages become the internal model: Melbourne ISO weeks, set kinds, grouping keys."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from coach.hevy.models import WorkoutsPage
from coach.model import MELBOURNE, SetKind, WeekId, from_raw_pages, from_raw_workout


def _raw_workout(start: str, **overrides) -> dict:
    base = {
        "id": "w-1",
        "title": "Session",
        "start_time": start,
        "end_time": start,
        "exercises": [
            {
                "index": 0,
                "title": "Bench Press (Barbell)",
                "exercise_template_id": "TPL00002",
                "superset_id": None,
                "sets": [
                    {"index": 0, "type": "warmup", "weight_kg": 40.0, "reps": 8, "rpe": None},
                    {"index": 1, "type": "normal", "weight_kg": 80.0, "reps": 5, "rpe": 8.0},
                    {"index": 2, "type": "dropset", "weight_kg": 60.0, "reps": 8, "rpe": 9.0},
                    {"index": 3, "type": "cluster", "weight_kg": 60.0, "reps": 3, "rpe": None},
                    {"index": 4, "type": "normal", "weight_kg": None, "reps": 10, "rpe": None},
                ],
            }
        ],
    }
    base.update(overrides)
    return base


def test_week_id_parse_format_and_shift() -> None:
    week = WeekId.parse("2026-W40")
    assert str(week) == "2026-W40"
    assert week.shift(-1) == WeekId(2026, 39)
    assert WeekId.parse("2026-W01").shift(-1) == WeekId(2025, 52)
    assert WeekId(2026, 53).shift(1) == WeekId(2027, 1)  # 2026 has 53 ISO weeks
    with pytest.raises(ValueError):
        WeekId.parse("2026-40")


def test_week_id_monday() -> None:
    assert WeekId.parse("2026-W40").monday().isoformat() == "2026-09-28"


def test_workout_week_uses_melbourne_local_date() -> None:
    # 13:30 UTC on Sunday 4 Oct 2026 is 00:30 on Monday 5 Oct in Melbourne (AEDT, UTC+11),
    # so the workout belongs to ISO week 2026-W41, not W40.
    workout = from_raw_workout(
        WorkoutsPage.model_validate(
            {"page": 1, "page_count": 1, "workouts": [_raw_workout("2026-10-04T13:30:00+00:00")]}
        ).workouts[0]
    )
    assert workout.start.tzinfo is not None
    assert workout.start.astimezone(MELBOURNE).isoformat() == "2026-10-05T00:30:00+11:00"
    assert workout.week == WeekId(2026, 41)
    assert workout.local_date.isoformat() == "2026-10-05"


def test_workout_week_before_melbourne_midnight_stays_in_prior_week() -> None:
    page = WorkoutsPage.model_validate(
        {"page": 1, "page_count": 1, "workouts": [_raw_workout("2026-10-04T12:30:00Z")]}
    )
    assert from_raw_workout(page.workouts[0]).week == WeekId(2026, 40)


def test_set_kinds_and_working_flag() -> None:
    page = WorkoutsPage.model_validate(
        {"page": 1, "page_count": 1, "workouts": [_raw_workout("2026-10-01T21:00:00Z")]}
    )
    sets = from_raw_workout(page.workouts[0]).exercises[0].sets
    assert [s.kind for s in sets] == [
        SetKind.WARMUP,
        SetKind.NORMAL,
        SetKind.DROPSET,
        SetKind.OTHER,
        SetKind.NORMAL,
    ]
    assert sets[3].raw_type == "cluster"
    assert [s.is_working for s in sets] == [False, True, True, True, True]
    assert sets[4].weight_kg is None and sets[4].reps == 10


def test_superset_flag() -> None:
    raw = _raw_workout("2026-10-01T21:00:00Z")
    raw["exercises"][0]["superset_id"] = 0
    page = WorkoutsPage.model_validate({"page": 1, "page_count": 1, "workouts": [raw]})
    assert from_raw_workout(page.workouts[0]).exercises[0].superset is True


def test_from_raw_pages_sorts_by_start_and_drops_duplicate_ids() -> None:
    later = _raw_workout("2026-10-02T21:00:00Z", id="w-2")
    earlier = _raw_workout("2026-10-01T21:00:00Z", id="w-1")
    duplicate = _raw_workout("2026-10-01T21:00:00Z", id="w-1")
    pages = [
        WorkoutsPage.model_validate({"page": 1, "page_count": 2, "workouts": [later, duplicate]}),
        WorkoutsPage.model_validate({"page": 2, "page_count": 2, "workouts": [earlier]}),
    ]
    workouts = from_raw_pages(pages)
    assert [w.id for w in workouts] == ["w-1", "w-2"]
    assert workouts[0].start == datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
