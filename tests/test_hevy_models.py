"""Raw Hevy shapes: strict on the fields we use, tolerant of the rest."""

import pytest
from pydantic import ValidationError

from coach.hevy.models import WorkoutCount, WorkoutsPage


def test_fixture_page_validates_and_keeps_unknown_fields(hevy_fixture) -> None:
    raw = hevy_fixture("workouts-page-1.json")
    raw["workouts"][0]["some_future_field"] = {"x": 1}
    page = WorkoutsPage.model_validate(raw)
    assert page.page == 1 and page.page_count == 3
    assert len(page.workouts) == 2
    first = page.workouts[0]
    assert first.start_time.tzinfo is not None
    assert first.exercises[0].title == "Squat (Barbell)"
    assert first.exercises[0].sets[0].type == "warmup"
    assert first.exercises[0].sets[2].weight_kg == 60.0
    assert first.exercises[0].sets[2].reps == 5
    assert first.model_extra["some_future_field"] == {"x": 1}


def test_missing_workouts_key_is_rejected(hevy_fixture) -> None:
    with pytest.raises(ValidationError):
        WorkoutsPage.model_validate(hevy_fixture("malformed-missing-workouts.json"))


def test_naive_start_time_is_rejected(hevy_fixture) -> None:
    with pytest.raises(ValidationError) as excinfo:
        WorkoutsPage.model_validate(hevy_fixture("malformed-naive-start-time.json"))
    assert "start_time" in str(excinfo.value)


def test_unknown_set_type_is_kept_as_text(hevy_fixture) -> None:
    raw = hevy_fixture("workouts-page-1.json")
    raw["workouts"][0]["exercises"][0]["sets"][0]["type"] = "cluster"
    page = WorkoutsPage.model_validate(raw)
    assert page.workouts[0].exercises[0].sets[0].type == "cluster"


def test_fractional_reps_are_rejected(hevy_fixture) -> None:
    raw = hevy_fixture("workouts-page-1.json")
    raw["workouts"][0]["exercises"][0]["sets"][2]["reps"] = 5.5
    with pytest.raises(ValidationError):
        WorkoutsPage.model_validate(raw)


def test_workout_count(hevy_fixture) -> None:
    assert WorkoutCount.model_validate(hevy_fixture("workouts-count.json")).workout_count == 6
