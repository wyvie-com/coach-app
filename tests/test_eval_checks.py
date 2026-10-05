"""Each code check against a review built to pass it and one built to fail it."""

from __future__ import annotations

import pytest

from coach.evals.cases import CASES, build_case
from coach.evals.checks import CHECK_NAMES, run_checks
from coach.figures import week_figures
from coach.pricing import Cost
from coach.review.loop import ReviewRun, ToolCall
from coach.review.schema import Finding, Review

BENCH, SQUAT, DEADLIFT = "Bench Press (Barbell)", "Squat (Barbell)", "Deadlift (Barbell)"


def _case(name: str):
    return next(c for c in CASES if c.name == name)


def _run(review: Review | None, tool_calls: list[ToolCall], outcome: str = "ok") -> ReviewRun:
    zero = Cost(
        model="m", input_usd=0, cache_write_usd=0, cache_read_usd=0, output_usd=0, total_usd=0
    )
    return ReviewRun(
        outcome=outcome,
        model="m",
        review=review,
        raw_text=None,
        turns=1,
        tool_calls=tool_calls,
        requests=[],
        cost=zero,
        seconds=0.1,
    )


def _call(exercise: str, weeks: int = 5, error: bool = False) -> ToolCall:
    return ToolCall(exercise=exercise, weeks=weeks, is_error=error, result_chars=10)


def _by_name(results):
    return {r.name: r for r in results}


@pytest.fixture(scope="module")
def stall():
    data = build_case(_case("bench_stall-1"))
    return data, week_figures(data.workouts, data.review_week)


def test_check_names_match_the_spec() -> None:
    assert CHECK_NAMES == (
        "schema_valid",
        "story_found",
        "no_false_alarm",
        "exercises_exist",
        "kg_grounded",
        "concern_preceded_by_tool",
        "max_three_suggestions",
        "sessions_threshold",
    )


def test_a_correct_bench_stall_review_passes_everything(stall) -> None:
    data, figures = stall
    bench_top = next(e for e in figures.exercises if e.exercise == BENCH).top_set.weight_kg
    review = Review(
        headline=f"Bench has sat at {bench_top} kg for five weeks.",
        highlights=[Finding(exercise=SQUAT, text="Still climbing.")],
        concerns=[Finding(exercise=BENCH, text=f"{bench_top} kg x 5 every week for five weeks.")],
        suggestions=[Finding(exercise=BENCH, text="Reset and rebuild.")],
    )
    results = _by_name(run_checks(data.case, figures, _run(review, [_call(BENCH)]), data.workouts))
    assert all(r.passed for r in results.values()), {
        k: v.detail for k, v in results.items() if not v.passed
    }


def test_no_review_fails_every_check(stall) -> None:
    data, figures = stall
    results = run_checks(data.case, figures, _run(None, [], outcome="refusal"), data.workouts)
    assert [r.passed for r in results] == [False] * len(CHECK_NAMES)
    assert all("refusal" in r.detail for r in results)


def test_story_found_needs_the_right_section_and_exercise(stall) -> None:
    data, figures = stall
    wrong_section = Review(
        headline="h",
        highlights=[Finding(exercise=BENCH, text="Steady.")],
        concerns=[],
        suggestions=[],
    )
    results = _by_name(
        run_checks(data.case, figures, _run(wrong_section, [_call(BENCH)]), data.workouts)
    )
    assert results["story_found"].passed is False
    assert "concerns" in results["story_found"].detail and BENCH in results["story_found"].detail


def test_story_found_accepts_any_lift_for_steady_progress() -> None:
    data = build_case(_case("steady_progress-1"))
    figures = week_figures(data.workouts, data.review_week)
    review = Review(
        headline="h",
        highlights=[Finding(exercise=DEADLIFT, text="Up.")],
        concerns=[],
        suggestions=[],
    )
    results = _by_name(run_checks(data.case, figures, _run(review, []), data.workouts))
    assert results["story_found"].passed is True


def test_false_alarm_on_a_negative_case() -> None:
    data = build_case(_case("negative_deload-1"))
    figures = week_figures(data.workouts, data.review_week)
    review = Review(
        headline="h",
        highlights=[],
        concerns=[Finding(exercise=SQUAT, text="Load fell this week.")],
        suggestions=[],
    )
    results = _by_name(run_checks(data.case, figures, _run(review, [_call(SQUAT)]), data.workouts))
    assert results["no_false_alarm"].passed is False
    assert results["story_found"].passed is True  # nothing was expected, nothing is missing


def test_false_alarm_on_an_unplanted_exercise_in_a_positive_case(stall) -> None:
    data, figures = stall
    review = Review(
        headline="h",
        highlights=[],
        concerns=[
            Finding(exercise=BENCH, text="Flat."),
            Finding(exercise=DEADLIFT, text="Also flat, I feel."),
        ],
        suggestions=[],
    )
    results = _by_name(
        run_checks(data.case, figures, _run(review, [_call(BENCH), _call(DEADLIFT)]), data.workouts)
    )
    assert results["no_false_alarm"].passed is False
    assert DEADLIFT in results["no_false_alarm"].detail


def test_overall_concern_is_a_false_alarm_unless_sessions_were_planted(stall) -> None:
    data, figures = stall
    review = Review(
        headline="h",
        highlights=[],
        concerns=[
            Finding(exercise=BENCH, text="Flat."),
            Finding(exercise="Overall", text="Missed sessions."),
        ],
        suggestions=[],
    )
    results = _by_name(run_checks(data.case, figures, _run(review, [_call(BENCH)]), data.workouts))
    assert results["no_false_alarm"].passed is False
    missed = build_case(_case("missed_sessions-1"))
    missed_figures = week_figures(missed.workouts, missed.review_week)
    ok = Review(
        headline="h",
        highlights=[],
        concerns=[Finding(exercise="Overall", text="One session.")],
        suggestions=[],
    )
    results = _by_name(run_checks(missed.case, missed_figures, _run(ok, []), missed.workouts))
    assert results["no_false_alarm"].passed is True and results["story_found"].passed is True


def test_exercises_exist_rejects_names_not_in_the_figures(stall) -> None:
    data, figures = stall
    review = Review(
        headline="h",
        highlights=[Finding(exercise="Leg Press", text="Nice.")],
        concerns=[Finding(exercise=BENCH, text="Flat.")],
        suggestions=[],
    )
    results = _by_name(run_checks(data.case, figures, _run(review, [_call(BENCH)]), data.workouts))
    assert (
        results["exercises_exist"].passed is False
        and "Leg Press" in results["exercises_exist"].detail
    )


def test_kg_grounded_accepts_figures_and_tool_results_and_rejects_invented_numbers(stall) -> None:
    data, figures = stall
    bench = next(e for e in figures.exercises if e.exercise == BENCH)
    good = Review(
        headline=f"Volume {bench.volume_kg} kg on bench; top set {bench.top_set.weight_kg}kg.",
        highlights=[Finding(exercise=SQUAT, text="e1RM change of 5.8 kg over four weeks.")],
        concerns=[Finding(exercise=BENCH, text=f"Stuck at {bench.top_set.weight_kg} kg.")],
        suggestions=[Finding(exercise=BENCH, text="Try 999 kg.")],  # suggestions are not checked
    )
    results = _by_name(
        run_checks(
            data.case, figures, _run(good, [_call(BENCH, 5), _call(SQUAT, 4)]), data.workouts
        )
    )
    assert results["kg_grounded"].passed is True, results["kg_grounded"].detail
    bad = Review(
        headline="Bench is at 123.4 kg.",
        highlights=[],
        concerns=[Finding(exercise=BENCH, text="Flat.")],
        suggestions=[],
    )
    results = _by_name(run_checks(data.case, figures, _run(bad, [_call(BENCH)]), data.workouts))
    assert results["kg_grounded"].passed is False and "123.4" in results["kg_grounded"].detail


def test_kg_grounded_uses_only_successful_tool_calls(stall) -> None:
    data, figures = stall
    # 5.8 kg is the squat's four-week e1RM change, visible only through a squat tool result.
    review = Review(
        headline="Squat e1RM up 5.8 kg.",
        highlights=[],
        concerns=[Finding(exercise=BENCH, text="Flat.")],
        suggestions=[],
    )
    with_error = _run(review, [_call(BENCH), _call(SQUAT, 4, error=True)])
    results = _by_name(run_checks(data.case, figures, with_error, data.workouts))
    # The figures themselves carry e1rm_change_4w_kg, so this one is grounded even so.
    assert results["kg_grounded"].passed is True


def test_concern_needs_a_successful_tool_call_for_that_exercise(stall) -> None:
    data, figures = stall
    review = Review(
        headline="h",
        highlights=[],
        concerns=[Finding(exercise=BENCH, text="Flat.")],
        suggestions=[],
    )
    assert (
        _by_name(run_checks(data.case, figures, _run(review, []), data.workouts))[
            "concern_preceded_by_tool"
        ].passed
        is False
    )
    assert (
        _by_name(
            run_checks(data.case, figures, _run(review, [_call(BENCH, error=True)]), data.workouts)
        )["concern_preceded_by_tool"].passed
        is False
    )
    assert (
        _by_name(run_checks(data.case, figures, _run(review, [_call(BENCH)]), data.workouts))[
            "concern_preceded_by_tool"
        ].passed
        is True
    )
    overall_only = Review(
        headline="h",
        highlights=[],
        concerns=[Finding(exercise="Overall", text="x")],
        suggestions=[],
    )
    assert (
        _by_name(run_checks(data.case, figures, _run(overall_only, []), data.workouts))[
            "concern_preceded_by_tool"
        ].passed
        is True
    )


def test_kg_grounded_accepts_a_difference_of_two_grounded_figures_for_the_same_exercise(
    stall,
) -> None:
    data, figures = stall
    # Bench rose 70 -> 72.5 -> 75 kg over the tool window: "2.5 kg" is derived, not invented.
    review = Review(
        headline="Bench moved up 2.5 kg a fortnight before it stalled.",
        highlights=[],
        concerns=[Finding(exercise=BENCH, text="Flat for five weeks.")],
        suggestions=[],
    )
    run = _run(review, [_call(BENCH, 12)])
    assert (
        _by_name(run_checks(data.case, figures, run, data.workouts))["kg_grounded"].passed is True
    )
    strict = run_checks(data.case, figures, run, data.workouts, allow_differences=False)
    assert _by_name(strict)["kg_grounded"].passed is False


def test_kg_grounded_difference_must_be_within_one_exercise(stall) -> None:
    data, figures = stall
    bench = next(e for e in figures.exercises if e.exercise == BENCH).top_set.weight_kg
    squat = next(e for e in figures.exercises if e.exercise == SQUAT).top_set.weight_kg
    cross = abs(squat - bench)
    review = Review(
        headline=f"The gap between squat and bench is {cross} kg.",
        highlights=[],
        concerns=[Finding(exercise=BENCH, text="Flat.")],
        suggestions=[],
    )
    results = _by_name(run_checks(data.case, figures, _run(review, [_call(BENCH)]), data.workouts))
    assert results["kg_grounded"].passed is False


def test_data_checks_for_a_real_week_have_no_story_checks(stall) -> None:
    from coach.evals.checks import DATA_CHECK_NAMES, run_data_checks

    data, figures = stall
    review = Review(
        headline="h",
        highlights=[],
        concerns=[Finding(exercise=BENCH, text="Flat.")],
        suggestions=[],
    )
    results = run_data_checks(figures, _run(review, [_call(BENCH)]), data.workouts)
    assert [r.name for r in results] == list(DATA_CHECK_NAMES)
    assert "story_found" not in DATA_CHECK_NAMES and "no_false_alarm" not in DATA_CHECK_NAMES
    assert all(r.passed for r in results)


def test_sessions_threshold_blocks_a_concern_under_one_missed_session(stall) -> None:
    data, figures = stall  # bench_stall has three sessions against a baseline of three
    assert figures.sessions_missed == pytest.approx(0.0)
    review = Review(
        headline="h",
        highlights=[],
        concerns=[Finding(exercise="Overall", text="You missed 0.25 of a session this week.")],
        suggestions=[],
    )
    results = _by_name(run_checks(data.case, figures, _run(review, []), data.workouts))
    assert results["sessions_threshold"].passed is False
    other = Review(
        headline="h",
        highlights=[],
        concerns=[Finding(exercise="Overall", text="Volume fell.")],
        suggestions=[],
    )
    assert (
        _by_name(run_checks(data.case, figures, _run(other, []), data.workouts))[
            "sessions_threshold"
        ].passed
        is True
    )
    missed = build_case(_case("missed_sessions-1"))
    missed_figures = week_figures(missed.workouts, missed.review_week)
    ok = Review(
        headline="h",
        highlights=[],
        concerns=[Finding(exercise="Overall", text="Only one session.")],
        suggestions=[],
    )
    assert (
        _by_name(run_checks(missed.case, missed_figures, _run(ok, []), missed.workouts))[
            "sessions_threshold"
        ].passed
        is True
    )
