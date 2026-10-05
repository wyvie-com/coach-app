"""Raw Hevy response shapes, as Pydantic models.

Strict about the fields the figures depend on (ids, timestamps, titles, template
ids, set type, weight, reps, RPE) and tolerant of everything else: every model
allows extra fields so a new Hevy field never breaks a pull. Timestamps must
carry a UTC offset; a naive string is rejected rather than assumed to be UTC,
because the week a workout belongs to depends on it.

Shapes follow the Hevy OpenAPI document (version 0.0.1) read on 2026-10-05; see
tests/fixtures/hevy/README.md for the field list.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict


class _Tolerant(BaseModel):
    model_config = ConfigDict(extra="allow")


class RawSet(_Tolerant):
    """One set. ``type`` is kept as text: the read schema lists the values in prose, not an enum."""

    index: int
    type: str
    weight_kg: float | None = None
    reps: int | None = None
    rpe: float | None = None


class RawExercise(_Tolerant):
    """One exercise within a workout. ``exercise_template_id`` is the join key across weeks."""

    index: int
    title: str
    exercise_template_id: str
    superset_id: int | None = None
    sets: list[RawSet]


class RawWorkout(_Tolerant):
    """One workout as Hevy returns it."""

    id: str
    title: str
    start_time: AwareDatetime
    end_time: AwareDatetime
    exercises: list[RawExercise]


class WorkoutsPage(_Tolerant):
    """The body of ``GET /v1/workouts``."""

    page: int
    page_count: int
    workouts: list[RawWorkout]


class WorkoutCount(_Tolerant):
    """The body of ``GET /v1/workouts/count``."""

    workout_count: int
