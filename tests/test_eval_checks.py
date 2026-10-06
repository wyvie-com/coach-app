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
        "comparisons_grounded",
        "flags_in_concerns",
        "pct_grounded",
        "deload_grounded",
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


def _review_with(highlight: Finding) -> Review:
    return Review(headline="h", highlights=[highlight], concerns=[], suggestions=[])


def test_comparisons_grounded_accepts_the_leader_and_rejects_another_exercise(stall) -> None:
    data, figures = stall
    leader = figures.leaders.e1rm_change_4w_pct
    assert leader is not None
    other = BENCH  # flat on every figure in this case, so it leads nothing
    assert other not in figures.leaders.model_dump().values()
    good = _review_with(Finding(exercise=leader, text="The largest four-week e1RM gain."))
    bad = _review_with(Finding(exercise=other, text="The largest four-week e1RM gain."))
    assert _by_name(run_checks(_case("bench_stall-1"), figures, _run(good, []), data.workouts))[
        "comparisons_grounded"
    ].passed
    result = _by_name(run_checks(_case("bench_stall-1"), figures, _run(bad, []), data.workouts))[
        "comparisons_grounded"
    ]
    assert not result.passed and other in result.detail and "largest" in result.detail


def test_comparisons_grounded_overall_superlative_must_name_a_leader(stall) -> None:
    data, figures = stall
    leader = figures.leaders.e1rm_change_4w_pct
    named = _review_with(Finding(exercise="Overall", text=f"{leader} grew fastest."))
    unnamed = _review_with(Finding(exercise="Overall", text="The squat grew fastest."))
    assert _by_name(run_checks(_case("bench_stall-1"), figures, _run(named, []), data.workouts))[
        "comparisons_grounded"
    ].passed
    assert not _by_name(
        run_checks(_case("bench_stall-1"), figures, _run(unnamed, []), data.workouts)
    )["comparisons_grounded"].passed


def test_comparisons_grounded_universal_claim_needs_a_full_count(stall) -> None:
    data, figures = stall
    assert figures.counts.e1rm_up_4w < figures.counts.exercises  # the bench is flat
    claim = _review_with(Finding(exercise="Overall", text="Every lift improved this month."))
    result = _by_name(run_checks(_case("bench_stall-1"), figures, _run(claim, []), data.workouts))[
        "comparisons_grounded"
    ]
    assert not result.passed and "Every lift improved" in result.detail
    trained = _review_with(Finding(exercise="Overall", text="Every lift was trained three times."))
    assert _by_name(run_checks(_case("bench_stall-1"), figures, _run(trained, []), data.workouts))[
        "comparisons_grounded"
    ].passed


def test_comparisons_grounded_lets_the_leader_say_it_led_all_exercises(stall) -> None:
    data, figures = stall
    leader = figures.leaders.e1rm_change_4w_pct
    led = _review_with(Finding(exercise=leader, text="Led all exercises with the largest gain."))
    assert _by_name(run_checks(_case("bench_stall-1"), figures, _run(led, []), data.workouts))[
        "comparisons_grounded"
    ].passed


def _checks(stall, review: Review, calls: list[ToolCall] | None = None):
    data, figures = stall
    return _by_name(
        run_checks(_case("bench_stall-1"), figures, _run(review, calls or []), data.workouts)
    )


def test_flags_in_concerns_needs_every_flag(stall) -> None:
    data, figures = stall
    assert [f.kind for f in figures.summary.flags] == ["stall"]
    carried = Review(
        headline="h",
        highlights=[],
        concerns=[Finding(exercise=BENCH, text="Unchanged for five weeks.")],
        suggestions=[],
    )
    dropped = Review(
        headline="h",
        highlights=[Finding(exercise=BENCH, text="Held steady at 80 kg.")],
        concerns=[],
        suggestions=[],
    )
    assert _checks(stall, carried)["flags_in_concerns"].passed
    result = _checks(stall, dropped)["flags_in_concerns"]
    assert not result.passed and "5 consecutive weeks" in result.detail


def test_pct_grounded_ties_a_percentage_to_its_exercise(stall) -> None:
    data, figures = stall
    row = next(e for e in figures.exercises if e.exercise == "Dumbbell Row")
    own = _review_with(
        Finding(exercise="Dumbbell Row", text=f"Up {row.e1rm_change_4w_pct}% over four weeks.")
    )
    moved = _review_with(
        Finding(exercise=SQUAT, text=f"Up {row.e1rm_change_4w_pct}% over four weeks.")
    )
    overall = _review_with(
        Finding(exercise="Overall", text=f"Best gain {row.e1rm_change_4w_pct} percent.")
    )
    invented = _review_with(Finding(exercise="Dumbbell Row", text="Up 42.0% this month."))
    assert _checks(stall, own)["pct_grounded"].passed
    assert not _checks(stall, moved)["pct_grounded"].passed
    assert _checks(stall, overall)["pct_grounded"].passed
    result = _checks(stall, invented)["pct_grounded"]
    assert not result.passed and "42%" in result.detail


def test_pct_grounded_accepts_a_tool_result_percentage(stall) -> None:
    from coach.figures import exercise_history

    data, figures = stall
    history = exercise_history(data.workouts, BENCH, weeks=8, ending=data.review_week)
    assert history.e1rm_change_pct is not None
    text = f"Up {history.e1rm_change_pct}% over eight weeks."
    review = _review_with(Finding(exercise=BENCH, text=text))
    assert _checks(stall, review, [_call(BENCH, 8)])["pct_grounded"].passed
    assert not _checks(stall, review)["pct_grounded"].passed  # no tool call, not in the figures


def test_deload_grounded_needs_a_deload_title(stall) -> None:
    claimed = _review_with(Finding(exercise="Overall", text="A deload week, fewer sessions."))
    result = _checks(stall, claimed)["deload_grounded"]
    assert not result.passed and "no Deload session title" in result.detail
    advised = Review(
        headline="h",
        highlights=[],
        concerns=[],
        suggestions=[Finding(exercise=BENCH, text="Consider a deload week to reset.")],
    )
    assert _checks(stall, advised)["deload_grounded"].passed  # advice, not a claim
    deload = build_case(_case("negative_deload-1"))
    figures = week_figures(deload.workouts, deload.review_week)
    assert figures.summary.deload
    ok = _by_name(run_checks(deload.case, figures, _run(claimed, []), deload.workouts))
    assert ok["deload_grounded"].passed
