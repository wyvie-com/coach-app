"""Each planted story is visible in the figures by code alone, before any model is involved.

These assertions are the ground truth the slice 4 checks build on: if a story is not
visible here, no review could be expected to find it.
"""

from __future__ import annotations

import pytest

from coach.evals.cases import CASES, Story, build_case
from coach.figures import exercise_history, week_figures

BENCH, SQUAT, DEADLIFT = "Bench Press (Barbell)", "Squat (Barbell)", "Deadlift (Barbell)"


def _by_name(cases, name):
    return next(c for c in cases if c.name == name)


@pytest.fixture(scope="module")
def built():
    return {case.name: build_case(case) for case in CASES}


def test_case_list_matches_the_spec() -> None:
    names = [c.name for c in CASES]
    assert len(names) == 15 and len(set(names)) == 15
    singles = [
        s for s in Story if s not in (Story.COMBINED, Story.NEGATIVE_QUIET, Story.NEGATIVE_DELOAD)
    ]
    for story in singles:
        assert sum(1 for c in CASES if c.story is story) == 2
    for story in (Story.COMBINED, Story.NEGATIVE_QUIET, Story.NEGATIVE_DELOAD):
        assert sum(1 for c in CASES if c.story is story) == 1


def test_every_case_passes_through_the_raw_models(built) -> None:
    for name, data in built.items():
        assert len(data.workouts) >= 30, name
        assert all(w.start.tzinfo is not None for w in data.workouts)
        assert data.review_week == data.workouts[-1].week


@pytest.mark.parametrize("case", [c for c in CASES if c.story is Story.STEADY_PROGRESS], ids=str)
def test_steady_progress_every_lift_rises(case, built) -> None:
    data = built[case.name]
    for lift in (BENCH, SQUAT, DEADLIFT):
        history = exercise_history(data.workouts, lift, weeks=8, ending=data.review_week)
        assert history.e1rm_change_kg > 5.0, lift


@pytest.mark.parametrize("case", [c for c in CASES if c.story is Story.BENCH_STALL], ids=str)
def test_bench_stall_is_flat_for_five_weeks(case, built) -> None:
    data = built[case.name]
    history = exercise_history(data.workouts, BENCH, weeks=5, ending=data.review_week)
    tops = {e.top_set_kg for e in history.weeks}
    assert len(tops) == 1, tops
    assert abs(history.e1rm_change_kg) < 0.5
    assert abs(history.rpe_change) < 0.5
    squat = exercise_history(data.workouts, SQUAT, weeks=5, ending=data.review_week)
    assert squat.e1rm_change_kg > 0


@pytest.mark.parametrize("case", [c for c in CASES if c.story is Story.SQUAT_PR], ids=str)
def test_squat_pr_beats_the_prior_twelve_weeks(case, built) -> None:
    data = built[case.name]
    history = exercise_history(data.workouts, SQUAT, weeks=12, ending=data.review_week.shift(-1))
    prior_max = max(e.e1rm_kg for e in history.weeks if e.e1rm_kg is not None)
    this_week = week_figures(data.workouts, data.review_week)
    squat = next(e for e in this_week.exercises if e.exercise == SQUAT)
    assert squat.e1rm_kg > prior_max + 2.0


@pytest.mark.parametrize("case", [c for c in CASES if c.story is Story.RISING_RPE], ids=str)
def test_rising_rpe_at_the_same_load(case, built) -> None:
    data = built[case.name]
    history = exercise_history(data.workouts, DEADLIFT, weeks=4, ending=data.review_week)
    assert len({e.top_set_kg for e in history.weeks}) == 1
    rpes = [e.mean_rpe for e in history.weeks]
    assert rpes == sorted(rpes) and rpes[-1] - rpes[0] >= 2.0


@pytest.mark.parametrize("case", [c for c in CASES if c.story is Story.MISSED_SESSIONS], ids=str)
def test_missed_sessions_against_baseline(case, built) -> None:
    data = built[case.name]
    figures = week_figures(data.workouts, data.review_week)
    assert figures.sessions == 1
    assert figures.baseline_sessions == pytest.approx(3.0)
    assert figures.sessions_missed == pytest.approx(2.0)


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.story is Story.DEADLIFT_REGRESSION], ids=str
)
def test_deadlift_regression_over_four_weeks(case, built) -> None:
    data = built[case.name]
    history = exercise_history(data.workouts, DEADLIFT, weeks=4, ending=data.review_week)
    assert history.e1rm_change_pct <= -5.0
    bench = exercise_history(data.workouts, BENCH, weeks=4, ending=data.review_week)
    assert bench.e1rm_change_kg >= 0


def test_combined_shows_all_three_stories(built) -> None:
    data = built["combined-1"]
    figures = week_figures(data.workouts, data.review_week)
    assert figures.sessions == 1 and figures.sessions_missed == pytest.approx(2.0)
    bench = exercise_history(data.workouts, BENCH, weeks=5, ending=data.review_week)
    assert len({e.top_set_kg for e in bench.weeks}) == 1
    prior = exercise_history(data.workouts, SQUAT, weeks=12, ending=data.review_week.shift(-1))
    squat = next(e for e in figures.exercises if e.exercise == SQUAT)
    assert squat.e1rm_kg > max(e.e1rm_kg for e in prior.weeks if e.e1rm_kg) + 2.0


def test_negative_quiet_has_nothing_to_report(built) -> None:
    data = built["negative_quiet-1"]
    figures = week_figures(data.workouts, data.review_week)
    assert figures.sessions == 3 and figures.sessions_missed == pytest.approx(0.0)
    for lift in (BENCH, SQUAT, DEADLIFT):
        history = exercise_history(data.workouts, lift, weeks=5, ending=data.review_week)
        assert history.e1rm_change_kg >= 0, lift
        assert len({e.top_set_kg for e in history.weeks}) >= 2, lift  # no five-week stall
        assert abs(history.rpe_change) < 1.0, lift


def test_negative_deload_is_a_planned_drop(built) -> None:
    data = built["negative_deload-1"]
    figures = week_figures(data.workouts, data.review_week)
    assert figures.sessions == 3
    assert all("Deload" in title for title in figures.session_titles)
    for lift in (BENCH, SQUAT, DEADLIFT):
        this = next(e for e in figures.exercises if e.exercise == lift)
        assert this.mean_rpe <= 7.0, lift
        assert this.e1rm_change_4w_pct < -5.0, lift
    prior = week_figures(data.workouts, data.review_week.shift(-1))
    assert prior.exercises and all(
        e.mean_rpe > 7.5 for e in prior.exercises if e.exercise in (BENCH, SQUAT, DEADLIFT)
    )


def test_expectations_name_sections_and_exercises() -> None:
    case = _by_name(CASES, "bench_stall-1")
    assert [(e.section, e.exercise) for e in case.expected] == [("concerns", BENCH)]
    assert _by_name(CASES, "missed_sessions-1").expected[0].exercise == "Overall"
    assert _by_name(CASES, "negative_quiet-1").expected == ()
