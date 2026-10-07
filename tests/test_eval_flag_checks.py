"""The flag checks against findings built to pass and to fail them.

Added after an audit found that a concern saying the bench "is progressing normally and
is not stalled" passed every code check on a planted bench stall (docs/findings.md
entry 13). Placement, carrying the flag and consistency with it are three separate
checks; each test names the kind of wrong finding it guards against.
"""

from __future__ import annotations

import pytest

from coach.evals.cases import CASES, build_case
from coach.evals.checks import run_checks
from coach.evals.flag_text import other_names, read
from coach.figures import Flag, week_figures
from coach.pricing import Cost
from coach.review.loop import ReviewRun, ToolCall
from coach.review.schema import Finding, Review

BENCH, SQUAT, DEADLIFT = "Bench Press (Barbell)", "Squat (Barbell)", "Deadlift (Barbell)"


def _built(name: str):
    data = build_case(next(c for c in CASES if c.name == name))
    return data, week_figures(data.workouts, data.review_week)


def _run(review: Review, calls: list[ToolCall]) -> ReviewRun:
    zero = Cost(
        model="m", input_usd=0, cache_write_usd=0, cache_read_usd=0, output_usd=0, total_usd=0
    )
    return ReviewRun(
        outcome="ok",
        model="m",
        review=review,
        raw_text=None,
        turns=1,
        tool_calls=calls,
        requests=[],
        cost=zero,
        seconds=0.0,
    )


def _call(exercise: str, weeks: int = 5) -> ToolCall:
    return ToolCall(exercise=exercise, weeks=weeks, is_error=False, result_chars=10)


def _review(concerns=(), highlights=()) -> Review:
    return Review(
        headline="Training review.",
        highlights=list(highlights),
        concerns=list(concerns),
        suggestions=[],
    )


def _results(built, review: Review, calls: list[ToolCall] | None = None, figures=None):
    data, computed = built
    run = _run(review, calls if calls is not None else [])
    return {r.name: r for r in run_checks(data.case, figures or computed, run, data.workouts)}


@pytest.fixture(scope="module")
def stall():
    return _built("bench_stall-1")


@pytest.fixture(scope="module")
def regression():
    return _built("deadlift_regression-1")


@pytest.fixture(scope="module")
def missed():
    return _built("missed_sessions-1")


def test_the_audit_counterexample_no_longer_passes_every_check(stall) -> None:
    # The audit's fixture, unchanged: placed correctly, says the opposite of the flag.
    review = _review(
        concerns=[Finding(exercise=BENCH, text="Bench is progressing normally and is not stalled.")]
    )
    results = _results(stall, review, [_call(BENCH)])
    assert not all(r.passed for r in results.values())
    assert results["expected_placement"].passed  # placement only: the bench is in concerns
    assert not results["flags_carried"].passed
    assert not results["flags_consistent"].passed
    assert "progressing" in results["flags_consistent"].detail


@pytest.mark.parametrize(
    "text",
    [
        "Top set unchanged at 80 kg x 5 for five consecutive weeks.",
        "Bench has stalled at 80 kg for 5 reps.",
        "Bench has not moved from 80 kg x 5 in five weeks.",
        "No progress on the bench for five weeks: still 80 kg x 5.",
        "Bench plateaued at 80 kg x 5.",
        "80 kg x 5 every week for five weeks.",
        "Bench progress has stalled for five weeks.",
        "Bench is stuck at 80 kg while the squat kept climbing.",
        "Bench has held at 80 kg x 5 for five weeks, with RPE rising from 7 to 8.",
        "The bench top set hasn't increased in five weeks.",
    ],
)
def test_valid_paraphrases_of_a_stall_pass_all_three(stall, text: str) -> None:
    results = _results(
        stall, _review(concerns=[Finding(exercise=BENCH, text=text)]), [_call(BENCH)]
    )
    for name in ("expected_placement", "flags_carried", "flags_consistent"):
        assert results[name].passed, (name, results[name].detail)


def test_missing_finding_fails_placement_and_carried(stall) -> None:
    review = _review(highlights=[Finding(exercise=BENCH, text="Held steady at 80 kg.")])
    results = _results(stall, review)
    assert not results["expected_placement"].passed
    assert not results["flags_carried"].passed
    assert "no concern" in results["flags_carried"].detail


@pytest.mark.parametrize(
    "text",
    [
        "Bench is progressing normally and is not stalled.",
        "Bench is not stalled; the top set rose to 82.5 kg.",
        "Bench has improved steadily over five weeks.",
        "No stall on the bench: it keeps climbing.",
    ],
)
def test_contradictory_findings_fail_consistency(stall, text: str) -> None:
    results = _results(
        stall, _review(concerns=[Finding(exercise=BENCH, text=text)]), [_call(BENCH)]
    )
    assert not results["flags_consistent"].passed, results["flags_consistent"].detail


def test_a_contradiction_elsewhere_fails_even_when_the_concern_is_right(stall) -> None:
    review = _review(
        concerns=[Finding(exercise=BENCH, text="Unchanged at 80 kg x 5 for five weeks.")],
        highlights=[Finding(exercise=BENCH, text="Bench is progressing well.")],
    )
    results = _results(stall, review, [_call(BENCH)])
    assert results["flags_carried"].passed
    assert not results["flags_consistent"].passed
    assert "highlight" in results["flags_consistent"].detail


def test_irrelevant_finding_is_placed_but_does_not_carry_the_flag(stall) -> None:
    review = _review(concerns=[Finding(exercise=BENCH, text="Bench grip width could be wider.")])
    results = _results(stall, review, [_call(BENCH)])
    assert results["expected_placement"].passed
    assert not results["flags_carried"].passed
    assert results["flags_consistent"].passed  # nothing it says is opposite; it says nothing


def test_wrong_reason_fails_carried_and_says_what_was_stated(stall, regression) -> None:
    fall_for_a_stall = _review(
        concerns=[Finding(exercise=BENCH, text="Bench e1RM is down 6% over four weeks.")]
    )
    result = _results(stall, fall_for_a_stall, [_call(BENCH)])["flags_carried"]
    assert not result.passed and "fall" in result.detail
    stall_for_a_fall = _review(
        concerns=[Finding(exercise=DEADLIFT, text="Deadlift top set unchanged for five weeks.")]
    )
    result = _results(regression, stall_for_a_fall, [_call(DEADLIFT)])["flags_carried"]
    assert not result.passed and "stall" in result.detail


def test_wrong_direction_fails_both_flag_checks(stall, regression) -> None:
    rise_for_a_stall = _review(
        concerns=[Finding(exercise=BENCH, text="Bench top set rose from 77.5 kg to 80 kg.")]
    )
    results = _results(stall, rise_for_a_stall, [_call(BENCH)])
    assert not results["flags_carried"].passed and not results["flags_consistent"].passed
    rise_for_a_fall = _review(
        concerns=[Finding(exercise=DEADLIFT, text="Deadlift e1RM up 7.5% over four weeks.")]
    )
    results = _results(regression, rise_for_a_fall, [_call(DEADLIFT)])
    assert not results["flags_carried"].passed and not results["flags_consistent"].passed
    correct = _review(
        concerns=[Finding(exercise=DEADLIFT, text="Deadlift e1RM down 7.5% over four weeks.")]
    )
    results = _results(regression, correct, [_call(DEADLIFT)])
    assert results["flags_carried"].passed and results["flags_consistent"].passed


@pytest.mark.parametrize(
    "text",
    [
        "Deadlift has regressed: the top set fell from 140 kg to 130 kg.",
        "Deadlift strength dropped 7.5% in four weeks.",
        "Deadlift is declining.",
    ],
)
def test_valid_paraphrases_of_a_fall_pass(regression, text: str) -> None:
    results = _results(
        regression, _review(concerns=[Finding(exercise=DEADLIFT, text=text)]), [_call(DEADLIFT)]
    )
    assert results["flags_carried"].passed and results["flags_consistent"].passed


def test_negated_fall_is_a_contradiction(regression) -> None:
    review = _review(
        concerns=[Finding(exercise=DEADLIFT, text="Deadlift is not declining; it is holding.")]
    )
    assert not _results(regression, review, [_call(DEADLIFT)])["flags_consistent"].passed


def test_two_flags_on_one_exercise_must_both_be_stated(stall) -> None:
    data, figures = stall
    drop = Flag(
        exercise=BENCH,
        kind="e1rm_drop_4w",
        value=-6.0,
        text="Bench Press (Barbell): e1RM down 6.0% over four weeks",
    )
    summary = figures.summary.model_copy(update={"flags": [*figures.summary.flags, drop]})
    doubled = figures.model_copy(update={"summary": summary})
    only_stall = _review(concerns=[Finding(exercise=BENCH, text="Bench has stalled at 80 kg x 5.")])
    result = _results(stall, only_stall, [_call(BENCH)], figures=doubled)["flags_carried"]
    assert not result.passed and "e1RM down 6.0%" in result.detail
    both = _review(
        concerns=[
            Finding(
                exercise=BENCH,
                text="Bench has stalled at 80 kg x 5 for five weeks and its e1RM is down 6%.",
            )
        ]
    )
    results = _results(stall, both, [_call(BENCH)], figures=doubled)
    assert results["flags_carried"].passed and results["flags_consistent"].passed
    separate = _review(
        concerns=[
            Finding(exercise=BENCH, text="Bench has stalled at 80 kg x 5."),
            Finding(exercise=BENCH, text="Bench e1RM fell 6% over four weeks."),
        ]
    )
    assert _results(stall, separate, [_call(BENCH)], figures=doubled)["flags_carried"].passed


@pytest.mark.parametrize(
    "text",
    [
        "Only one session this week against a baseline of 3.0.",
        "Two sessions missed against the usual three.",
        "You trained once this week.",
    ],
)
def test_missed_sessions_paraphrases_pass(missed, text: str) -> None:
    results = _results(missed, _review(concerns=[Finding(exercise="Overall", text=text)]))
    for name in ("expected_placement", "flags_carried", "flags_consistent"):
        assert results[name].passed, (name, results[name].detail)


def test_missed_sessions_contradiction_and_irrelevance(missed) -> None:
    full = _review(
        concerns=[Finding(exercise="Overall", text="All three sessions done; none missed.")]
    )
    results = _results(missed, full)
    assert not results["flags_carried"].passed and not results["flags_consistent"].passed
    off_topic = _review(concerns=[Finding(exercise="Overall", text="Sleep was short this week.")])
    results = _results(missed, off_topic)
    assert results["expected_placement"].passed and not results["flags_carried"].passed


def test_negative_case_reports_not_applicable_instead_of_passing() -> None:
    quiet = _built("negative_quiet-1")
    results = _results(quiet, _review(highlights=[Finding(exercise=SQUAT, text="Up again.")]))
    placement = results["expected_placement"]
    assert placement.applicable is False and "negative case" in placement.detail
    for name in ("flags_carried", "flags_consistent"):
        assert results[name].applicable is False and "no flags" in results[name].detail
    assert results["no_false_alarm"].applicable and results["no_false_alarm"].passed


def test_flag_checks_do_not_apply_to_a_positive_case_without_flags() -> None:
    pr = _built("squat_pr-1")
    results = _results(pr, _review(highlights=[Finding(exercise=SQUAT, text="New best.")]))
    assert results["expected_placement"].applicable and results["expected_placement"].passed
    assert not results["flags_carried"].applicable and not results["flags_consistent"].applicable


def test_known_limits_are_pinned(stall) -> None:
    # Documented boundaries (docs/checks.md). A change that closes one should update this test.
    headline_only = Review(
        headline="Bench is progressing well.",
        highlights=[],
        concerns=[Finding(exercise=BENCH, text="Unchanged at 80 kg x 5 for five weeks.")],
        suggestions=[],
    )
    assert _results(stall, headline_only, [_call(BENCH)])["flags_consistent"].passed
    wrong_count = _review(
        concerns=[Finding(exercise=BENCH, text="Unchanged at 80 kg x 5 for two weeks.")]
    )
    results = _results(stall, wrong_count, [_call(BENCH)])
    assert results["flags_carried"].passed and results["flags_consistent"].passed


@pytest.mark.parametrize(
    "text",
    [
        "Deadlift top set unchanged at 140 kg x 5 for five weeks, and the rising RPE shows it "
        "is getting harder.",
        "Deadlift has held at 140 kg x 5 for five weeks while effort climbed from RPE 7 to 9.5.",
        "Deadlift effort rose from RPE 7 to 9.5 at the same 140 kg x 5 top set.",
    ],
)
def test_rising_effort_beside_a_stall_is_not_read_as_progress(text: str) -> None:
    # The rising-effort story: the deadlift's top set is flagged as a stall while RPE climbs.
    rising = _built("rising_rpe-1")
    results = _results(
        rising, _review(concerns=[Finding(exercise=DEADLIFT, text=text)]), [_call(DEADLIFT)]
    )
    assert results["flags_carried"].passed, results["flags_carried"].detail
    assert results["flags_consistent"].passed, results["flags_consistent"].detail


@pytest.mark.parametrize(
    "text",
    [
        "Bench has stalled at 80 kg x 5 for five weeks after steady progress earlier in the block.",
        "Bench has held at 80 kg x 5 for five weeks, halting the steady weekly advances.",
        "Bench has had no change at 80 kg x 5 since its last increase.",
    ],
)
def test_earlier_or_halted_progress_is_not_a_current_claim(stall, text: str) -> None:
    results = _results(
        stall, _review(concerns=[Finding(exercise=BENCH, text=text)]), [_call(BENCH)]
    )
    assert results["flags_carried"].passed, results["flags_carried"].detail
    assert results["flags_consistent"].passed, results["flags_consistent"].detail


def test_a_current_rise_after_a_stall_is_still_a_contradiction(stall) -> None:
    review = _review(
        concerns=[Finding(exercise=BENCH, text="Bench stalled, then rose to 82.5 kg this week.")]
    )
    assert not _results(stall, review, [_call(BENCH)])["flags_consistent"].passed


@pytest.mark.parametrize(
    "text",
    ["Bench improved last week.", "Bench has been progressing since week 36."],
)
def test_recent_progress_is_a_contradiction(stall, text: str) -> None:
    review = _review(concerns=[Finding(exercise=BENCH, text=text)])
    assert not _results(stall, review, [_call(BENCH)])["flags_consistent"].passed


@pytest.mark.parametrize(
    "name, exercise, text",
    [
        ("bench_stall-1", BENCH, "Bench has been the same for the last five weeks."),
        ("bench_stall-1", BENCH, "Bench top set is the same as five weeks ago."),
        ("bench_stall-1", BENCH, "Bench hasn't gone up in five weeks."),
        ("bench_stall-1", BENCH, "Bench at 80 kg x 5 for the past five weeks."),
        ("deadlift_regression-1", DEADLIFT, "Deadlift has gone backwards over four weeks."),
        ("deadlift_regression-1", DEADLIFT, "Deadlift top set slid from 140 kg to 130 kg."),
        ("missed_sessions-1", "Overall", "One of three planned sessions completed."),
    ],
)
def test_more_everyday_paraphrases_carry_the_flag(name: str, exercise: str, text: str) -> None:
    built = _built(name)
    calls = [] if exercise == "Overall" else [_call(exercise)]
    results = _results(built, _review(concerns=[Finding(exercise=exercise, text=text)]), calls)
    assert results["flags_carried"].passed, results["flags_carried"].detail
    assert results["flags_consistent"].passed, results["flags_consistent"].detail


# The flagged exercise's own name. Found on a real week (docs/findings.md entry 14): a concern
# naming Seated Incline Curl was read as being about Incline Bench Press, whose short name
# "incline" is also a word of the curl's name, so the stall it stated was missed.
INCLINE_CURL, INCLINE_PRESS = "Seated Incline Curl (Dumbbell)", "Incline Bench Press (Barbell)"


def _renamed(built, names: dict[str, str]):
    """The case's figures with exercises renamed, flags included, to make two names collide."""
    _, figures = built
    exercises = [
        e.model_copy(update={"exercise": names.get(e.exercise, e.exercise)})
        for e in figures.exercises
    ]
    flags = [
        f.model_copy(
            update={
                "exercise": names.get(f.exercise, f.exercise),
                "text": f.text.replace(f.exercise, names.get(f.exercise, f.exercise)),
            }
        )
        for f in figures.summary.flags
    ]
    summary = figures.summary.model_copy(update={"flags": flags})
    return figures.model_copy(update={"exercises": exercises, "summary": summary})


@pytest.mark.parametrize(
    "names, flagged, text",
    [
        (
            {BENCH: INCLINE_CURL, SQUAT: INCLINE_PRESS},
            INCLINE_CURL,
            "Seated Incline Curl has held at 80 kg x 5 for 5 consecutive weeks and needs "
            "progression.",
        ),
        (
            {BENCH: "Romanian Deadlift (Barbell)"},
            "Romanian Deadlift (Barbell)",
            "Romanian Deadlift has held at 80 kg x 5 for five weeks.",
        ),
        (
            {BENCH: "Straight Arm Lat Pulldown (Cable)"},
            "Straight Arm Lat Pulldown (Cable)",
            "Straight Arm Lat Pulldown has stalled at 80 kg x 5 for five weeks.",
        ),
        (
            {BENCH: "Incline Bench Press (Dumbbell)", SQUAT: "Incline Bench Press (Smith Machine)"},
            "Incline Bench Press (Dumbbell)",
            "Incline Bench Press has held at 80 kg x 5 for five weeks.",
        ),
    ],
)
def test_another_lifts_name_inside_the_flagged_name_does_not_hide_the_finding(
    stall, names: dict[str, str], flagged: str, text: str
) -> None:
    # Each week also holds a lift whose prose name is part of the flagged one's name:
    # "incline" (Incline Bench Press), "deadlift" (Deadlift), "lat pulldown" (Lat Pulldown),
    # or all of it, for two variants of one lift.
    figures = _renamed(stall, names)
    review = _review(concerns=[Finding(exercise=flagged, text=text)])
    results = _results(stall, review, figures=figures)
    assert results["flags_carried"].passed, results["flags_carried"].detail
    assert results["flags_consistent"].passed, results["flags_consistent"].detail


def test_a_longer_name_containing_the_flagged_one_is_still_another_lift() -> None:
    # Guards the fix: "lat pulldown" inside "straight arm lat pulldown" is not the flagged
    # exercise. "Straight" is shared by two lifts here, so only the full name identifies it.
    names = ["Lat Pulldown (Cable)", "Straight Arm Lat Pulldown (Cable)", "Straight Leg Deadlift"]
    text = (
        "Lat Pulldown has held at 60 kg x 10 for five weeks, while straight arm lat pulldown rose."
    )
    reading = read("stall", text, other_names(names[0], names), own=names[0])
    assert reading.states and reading.opposite is None


def test_cue_words_in_the_flagged_name_are_not_read_as_claims() -> None:
    # "Decline" is a word for a fall; as part of the exercise's own name it claims nothing.
    names = ["Decline Bench Press (Barbell)", SQUAT]
    others = other_names(names[0], names)
    text = "Decline Bench Press has been at 70 kg x 6 for five weeks."
    assert read("stall", text, others, own=names[0]).states  # the duration states the stall
    assert not read("e1rm_drop_4w", text, others, own=names[0]).states  # and states no fall


def test_known_limit_a_shortened_flagged_name_can_still_read_as_another_lift() -> None:
    # Pinned (docs/checks.md): only the title, with or without its equipment, is read as the
    # flagged exercise's name. "The incline curl" still contains Incline Bench Press's short
    # name, so the clause is read as being about the press. A change that closes this should
    # update this test.
    names = [INCLINE_CURL, INCLINE_PRESS]
    text = "The incline curl has held at 80 kg x 5 for five weeks."
    assert not read("stall", text, other_names(INCLINE_CURL, names), own=INCLINE_CURL).states
