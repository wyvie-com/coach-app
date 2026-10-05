"""Figures are pure functions of the internal model; every rule is written down in figures.py."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from coach.figures import UnknownExerciseError, epley, exercise_history, week_figures
from coach.model import MELBOURNE, Exercise, Set, SetKind, WeekId, Workout

W40 = WeekId(2026, 40)


def _set(
    kind: SetKind,
    weight: float | None,
    reps: int | None,
    rpe: float | None = None,
    raw_type: str | None = None,
) -> Set:
    return Set(
        index=0, kind=kind, raw_type=raw_type or kind.value, weight_kg=weight, reps=reps, rpe=rpe
    )


def _workout(week: WeekId, day: int, exercises: list[Exercise], wid: str | None = None) -> Workout:
    start = datetime.combine(week.monday() + timedelta(days=day), datetime.min.time()).replace(
        hour=7, minute=30, tzinfo=MELBOURNE
    )
    return Workout(
        id=wid or f"{week}-{day}",
        title="Session",
        start=start,
        end=start + timedelta(hours=1),
        exercises=tuple(exercises),
    )


def _bench(
    top: float, reps: int = 5, rpe: float | None = 8.0, title: str = "Bench Press (Barbell)"
):
    return Exercise(
        template_id="TPL00002",
        title=title,
        superset=False,
        sets=(
            _set(SetKind.WARMUP, top * 0.5, 8),
            _set(SetKind.NORMAL, top, reps, rpe),
            _set(SetKind.NORMAL, top, reps, rpe),
        ),
    )


def test_epley() -> None:
    assert epley(100.0, 1) == 100.0
    assert epley(100.0, 5) == pytest.approx(116.7, abs=0.05)
    assert epley(60.0, 10) == pytest.approx(80.0)


def test_week_figures_excludes_warmups_and_null_sets() -> None:
    exercise = Exercise(
        template_id="TPL00001",
        title="Squat (Barbell)",
        superset=True,
        sets=(
            _set(SetKind.WARMUP, 60.0, 5),
            _set(SetKind.NORMAL, 100.0, 5, 8.0),
            _set(SetKind.NORMAL, 100.0, 5, 9.0),
            _set(SetKind.DROPSET, 80.0, 8, 9.5),
            _set(SetKind.OTHER, 80.0, 3, raw_type="cluster"),
            _set(SetKind.NORMAL, None, 10),
        ),
    )
    figures = week_figures([_workout(W40, 0, [exercise])], W40)
    assert figures.week == "2026-W40"
    assert figures.sessions == 1
    squat = figures.exercises[0]
    assert squat.exercise == "Squat (Barbell)"
    assert squat.superset is True
    assert squat.warmup_sets == 1
    assert squat.working_sets == 5
    assert squat.other_sets == 1
    assert squat.volume_kg == pytest.approx(100 * 5 + 100 * 5 + 80 * 8 + 80 * 3)
    assert squat.top_set is not None
    assert (squat.top_set.weight_kg, squat.top_set.reps, squat.top_set.rpe) == (100.0, 5, 9.0)
    assert squat.e1rm_kg == pytest.approx(epley(100.0, 5), abs=0.05)
    assert squat.mean_rpe == pytest.approx((8.0 + 9.0 + 9.5) / 3, abs=0.01)
    assert figures.warnings == ["1 set with an unrecognised type was counted as 'other': cluster"]


def test_top_set_tie_prefers_more_reps() -> None:
    exercise = Exercise(
        template_id="TPL00002",
        title="Bench Press (Barbell)",
        superset=False,
        sets=(_set(SetKind.NORMAL, 80.0, 3, 8.0), _set(SetKind.NORMAL, 80.0, 6, 9.0)),
    )
    top = week_figures([_workout(W40, 0, [exercise])], W40).exercises[0].top_set
    assert top is not None and top.reps == 6


def test_exercises_grouped_by_template_id_with_latest_title() -> None:
    old = _workout(W40, 0, [_bench(80.0, title="Bench (Barbell)")])
    new = _workout(W40, 2, [_bench(82.5, title="Bench Press (Barbell)")])
    figures = week_figures([old, new], W40)
    assert len(figures.exercises) == 1
    bench = figures.exercises[0]
    assert bench.exercise == "Bench Press (Barbell)"
    assert bench.sessions == 2
    assert bench.top_set is not None and bench.top_set.weight_kg == 82.5


def test_sessions_baseline_is_mean_of_prior_four_weeks() -> None:
    workouts = []
    for back, count in ((4, 3), (3, 3), (2, 2), (1, 4)):
        week = W40.shift(-back)
        workouts += [_workout(week, d, [_bench(80.0)]) for d in range(count)]
    workouts += [_workout(W40, 0, [_bench(80.0)])]
    figures = week_figures(workouts, W40)
    assert figures.sessions == 1
    assert figures.baseline_sessions == pytest.approx(3.0)
    assert figures.sessions_missed == pytest.approx(2.0)


def test_sessions_baseline_with_fewer_than_four_prior_weeks() -> None:
    workouts = [_workout(W40.shift(-1), d, [_bench(80.0)]) for d in range(2)]
    workouts += [_workout(W40.shift(-2), d, [_bench(80.0)]) for d in range(4)]
    workouts += [_workout(W40, 0, [_bench(80.0)])]
    figures = week_figures(workouts, W40)
    assert figures.baseline_sessions == pytest.approx(3.0)


def test_sessions_baseline_counts_an_empty_week_between_data_as_zero() -> None:
    workouts = [_workout(W40.shift(-3), d, [_bench(80.0)]) for d in range(4)]
    workouts += [_workout(W40.shift(-1), d, [_bench(80.0)]) for d in range(2)]
    workouts += [_workout(W40, 0, [_bench(80.0)])]
    figures = week_figures(workouts, W40)
    # Weeks -3, -2 (empty, inside the data range) and -1 count; week -4 predates the data.
    assert figures.baseline_sessions == pytest.approx((4 + 0 + 2) / 3)


def test_sessions_baseline_is_none_without_prior_data() -> None:
    figures = week_figures([_workout(W40, 0, [_bench(80.0)])], W40)
    assert figures.baseline_sessions is None and figures.sessions_missed is None


def test_week_with_no_workouts_has_zero_sessions_and_no_exercises() -> None:
    figures = week_figures([_workout(W40.shift(-1), 0, [_bench(80.0)])], W40)
    assert figures.sessions == 0 and figures.exercises == []
    assert figures.baseline_sessions == pytest.approx(1.0)


def test_exercise_history_windows_of_one_and_twelve_weeks() -> None:
    workouts = [_workout(W40.shift(-back), 0, [_bench(70.0 + back)]) for back in range(0, 12)]
    one = exercise_history(workouts, "Bench Press (Barbell)", weeks=1, ending=W40)
    assert [e.week for e in one.weeks] == ["2026-W40"]
    assert one.weeks[0].top_set_kg == 70.0

    twelve = exercise_history(workouts, "Bench Press (Barbell)", weeks=12, ending=W40)
    assert len(twelve.weeks) == 12
    assert twelve.weeks[0].week == "2026-W29" and twelve.weeks[-1].week == "2026-W40"
    assert twelve.weeks[0].top_set_kg == 81.0
    # 81 -> 70 kg at 5 reps is a regression; the change is first week to last week.
    assert twelve.e1rm_change_kg == pytest.approx(epley(70.0, 5) - epley(81.0, 5), abs=0.1)
    assert twelve.e1rm_change_pct < 0


def test_exercise_history_fills_missing_weeks_with_empty_entries() -> None:
    workouts = [_workout(W40, 0, [_bench(80.0)]), _workout(W40.shift(-2), 0, [_bench(80.0)])]
    history = exercise_history(workouts, "Bench Press (Barbell)", weeks=3, ending=W40)
    assert [e.sessions for e in history.weeks] == [1, 0, 1]
    assert history.weeks[1].top_set_kg is None and history.weeks[1].e1rm_kg is None


def test_exercise_history_rejects_out_of_range_window() -> None:
    workouts = [_workout(W40, 0, [_bench(80.0)])]
    with pytest.raises(ValueError):
        exercise_history(workouts, "Bench Press (Barbell)", weeks=0, ending=W40)
    with pytest.raises(ValueError):
        exercise_history(workouts, "Bench Press (Barbell)", weeks=13, ending=W40)


def test_exercise_history_unknown_name_lists_known_names() -> None:
    workouts = [_workout(W40, 0, [_bench(80.0)])]
    with pytest.raises(UnknownExerciseError) as excinfo:
        exercise_history(workouts, "Bench", weeks=4, ending=W40)
    assert "Bench Press (Barbell)" in str(excinfo.value)
    # Case-insensitive match is accepted; the figures use the exact title.
    assert exercise_history(workouts, "bench press (barbell)", weeks=1, ending=W40).exercise == (
        "Bench Press (Barbell)"
    )


def test_four_week_change_in_week_figures() -> None:
    workouts = [_workout(W40.shift(-back), 0, [_bench(80.0 - 2.5 * back)]) for back in range(5)]
    bench = week_figures(workouts, W40).exercises[0]
    assert bench.e1rm_change_4w_kg == pytest.approx(epley(80.0, 5) - epley(70.0, 5), abs=0.1)
    assert bench.e1rm_change_4w_pct == pytest.approx(
        100 * (epley(80.0, 5) / epley(70.0, 5) - 1), abs=0.1
    )


def test_e1rm_is_not_estimated_above_ten_reps() -> None:
    exercise = Exercise(
        template_id="TPL00007",
        title="Calf Press (Machine)",
        superset=False,
        sets=(_set(SetKind.NORMAL, 195.0, 20, None), _set(SetKind.NORMAL, 195.0, 18, None)),
    )
    calf = week_figures([_workout(W40, 0, [exercise])], W40).exercises[0]
    assert calf.e1rm_kg is None
    assert calf.top_set is not None and calf.top_set.weight_kg == 195.0
    assert calf.volume_kg == pytest.approx(195 * 38)
    history = exercise_history(
        [_workout(W40, 0, [exercise])], "Calf Press (Machine)", weeks=1, ending=W40
    )
    assert history.weeks[0].e1rm_kg is None and history.weeks[0].top_set_kg == 195.0


def test_e1rm_uses_the_best_set_at_or_under_ten_reps() -> None:
    exercise = Exercise(
        template_id="TPL00002",
        title="Bench Press (Barbell)",
        superset=False,
        sets=(_set(SetKind.NORMAL, 60.0, 15, None), _set(SetKind.NORMAL, 80.0, 6, None)),
    )
    bench = week_figures([_workout(W40, 0, [exercise])], W40).exercises[0]
    assert bench.e1rm_kg == pytest.approx(epley(80.0, 6), abs=0.05)


def test_rep_pr_at_matched_load_against_prior_twelve_weeks() -> None:
    # 90 kg for 6 reps four weeks ago, 90 kg for 8 reps this week: a rep PR at the same load.
    earlier = _workout(W40.shift(-4), 0, [_bench(90.0, reps=6)])
    this = _workout(W40, 0, [_bench(90.0, reps=8)])
    bench = week_figures([earlier, this], W40).exercises[0]
    assert bench.matched_load_prior_best_reps == 6
    assert bench.rep_pr is True


def test_no_rep_pr_when_reps_equal_or_load_is_new() -> None:
    same = [
        _workout(W40.shift(-2), 0, [_bench(90.0, reps=8)]),
        _workout(W40, 0, [_bench(90.0, reps=8)]),
    ]
    bench = week_figures(same, W40).exercises[0]
    assert bench.matched_load_prior_best_reps == 8 and bench.rep_pr is False
    new_load = [
        _workout(W40.shift(-2), 0, [_bench(85.0, reps=8)]),
        _workout(W40, 0, [_bench(90.0, reps=8)]),
    ]
    bench = week_figures(new_load, W40).exercises[0]
    assert bench.matched_load_prior_best_reps is None and bench.rep_pr is False


def test_rep_pr_ignores_loads_older_than_twelve_weeks() -> None:
    old = _workout(W40.shift(-13), 0, [_bench(90.0, reps=6)])
    this = _workout(W40, 0, [_bench(90.0, reps=8)])
    bench = week_figures([old, this], W40).exercises[0]
    assert bench.matched_load_prior_best_reps is None and bench.rep_pr is False


def test_top_set_unchanged_weeks_counts_back_from_the_latest_week() -> None:
    loads = {4: 75.0, 3: 80.0, 2: 80.0, 1: 80.0, 0: 80.0}  # weeks back -> top load, 5 reps each
    workouts = [_workout(W40.shift(-back), 0, [_bench(load)]) for back, load in loads.items()]
    history = exercise_history(workouts, "Bench Press (Barbell)", weeks=6, ending=W40)
    assert history.top_set_unchanged_weeks == 4
    moved = workouts + [_workout(W40.shift(1), 0, [_bench(82.5)])]
    assert (
        exercise_history(
            moved, "Bench Press (Barbell)", weeks=6, ending=W40.shift(1)
        ).top_set_unchanged_weeks
        == 1
    )
    same_load_more_reps = workouts + [_workout(W40.shift(1), 0, [_bench(80.0, reps=6)])]
    assert (
        exercise_history(
            same_load_more_reps, "Bench Press (Barbell)", weeks=6, ending=W40.shift(1)
        ).top_set_unchanged_weeks
        == 1
    )


def test_week_figures_carry_the_unchanged_weeks_count_over_twelve_weeks() -> None:
    loads = {4: 75.0, 3: 80.0, 2: 80.0, 1: 80.0, 0: 80.0}
    workouts = [_workout(W40.shift(-back), 0, [_bench(load)]) for back, load in loads.items()]
    assert week_figures(workouts, W40).exercises[0].top_set_unchanged_weeks == 4
    risen = workouts + [_workout(W40.shift(1), 0, [_bench(82.5)])]
    assert week_figures(risen, W40.shift(1)).exercises[0].top_set_unchanged_weeks == 1
    flat_for_long = [_workout(W40.shift(-back), 0, [_bench(80.0)]) for back in range(14)]
    assert week_figures(flat_for_long, W40).exercises[0].top_set_unchanged_weeks == 12


def test_top_set_unchanged_weeks_skips_empty_weeks_and_is_none_without_data() -> None:
    workouts = [_workout(W40, 0, [_bench(80.0)]), _workout(W40.shift(-2), 0, [_bench(80.0)])]
    history = exercise_history(workouts, "Bench Press (Barbell)", weeks=4, ending=W40)
    assert history.top_set_unchanged_weeks == 2
    none = exercise_history(workouts, "Bench Press (Barbell)", weeks=1, ending=W40.shift(-1))
    assert none.top_set_unchanged_weeks is None
