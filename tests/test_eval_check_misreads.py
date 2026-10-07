"""Correct sentences the code checks used to fail, and the errors they must still catch.

Re-scoring Claude's stored reviews (docs/findings.md entry 15) found 35 failures that were the
checks misreading a correct review. Each test below rewrites one pattern on a synthetic case
and pairs it with a sentence that is wrong in the same place, so a fix cannot simply wave the
pattern through.
"""

from __future__ import annotations

import pytest

from coach.evals.cases import CASES, build_case
from coach.evals.checks import run_checks
from coach.figures import week_figures
from coach.pricing import Cost
from coach.review.loop import ReviewRun
from coach.review.schema import Finding, Review

BENCH, SQUAT, DEADLIFT = "Bench Press (Barbell)", "Squat (Barbell)", "Deadlift (Barbell)"
LAT, OHP, ROW = "Lat Pulldown (Cable)", "Overhead Press (Barbell)", "Dumbbell Row"


def _built(name: str):
    data = build_case(next(c for c in CASES if c.name == name))
    return data, week_figures(data.workouts, data.review_week)


def _check(built, finding: Finding, section: str = "highlights", figures=None):
    data, computed = built
    review = Review(headline="Training review.", highlights=[], concerns=[], suggestions=[])
    review = review.model_copy(update={section: [finding]})
    zero = Cost(
        model="m", input_usd=0, cache_write_usd=0, cache_read_usd=0, output_usd=0, total_usd=0
    )
    run = ReviewRun(
        outcome="ok",
        model="m",
        review=review,
        raw_text=None,
        turns=1,
        tool_calls=[],
        requests=[],
        cost=zero,
        seconds=0.0,
    )
    return {r.name: r for r in run_checks(data.case, figures or computed, run, data.workouts)}


@pytest.fixture(scope="module")
def stall():
    # Four-week e1RM: Row 15.4%, Overhead Press 9.1%, Lat Pulldown 8.7%, Squat 4.5%,
    # Deadlift 3.6%, Bench 0.0%. Five of six up on e1RM and on volume, none down.
    return _built("bench_stall-1")


@pytest.fixture(scope="module")
def quiet():
    # Every lift up. Four-week e1RM: Row 15.4%, Overhead Press 10.0%, Lat Pulldown 9.5%,
    # Bench 6.7%, Squat 4.8%, Deadlift 3.7%.
    return _built("negative_quiet-1")


@pytest.fixture(scope="module")
def deload():
    # A titled deload: every lift down. Four-week e1RM: Row -2.7% (fell least), Overhead Press
    # -7.3%, Lat Pulldown -8.0%, Bench -10.0%, Squat -10.9%, Deadlift -12.1% (fell most).
    return _built("negative_deload-1")


def _comparisons(built, exercise: str, text: str, section: str = "highlights", figures=None):
    return _check(built, Finding(exercise=exercise, text=text), section, figures)[
        "comparisons_grounded"
    ]


# --- superlatives: a place is checked against the ranking, not waved through ---------------


def test_a_true_second_place_passes_and_a_false_one_fails(stall) -> None:
    assert _comparisons(stall, OHP, "Up 9.1% over four weeks, the second-largest gain.").passed
    assert _comparisons(stall, OHP, "The second strongest improvement after the row.").passed
    third = _comparisons(stall, LAT, "Up 8.7% over four weeks, the second-strongest gain.")
    assert not third.passed and "second" in third.detail


def test_one_of_the_largest_needs_a_place_in_the_top_half(stall) -> None:
    assert _comparisons(stall, OHP, "One of the largest gains this week.").passed
    # The bench is last on every figure once its volume is set below the others.
    bench = next(e for e in stall[1].exercises if e.exercise == BENCH)
    lowest = bench.model_copy(update={"volume_kg": 100.0})
    exercises = [lowest if e.exercise == BENCH else e for e in stall[1].exercises]
    figures = stall[1].model_copy(update={"exercises": exercises})
    result = _comparisons(stall, BENCH, "One of the largest gains this week.", figures=figures)
    assert not result.passed


@pytest.mark.parametrize(
    "text",
    [
        "Jumped to 62.5 kg for 5 reps, the strongest showing yet.",
        "62.5 kg for 5 reps, the strongest top set in this eight-week period.",
        "The strongest e1RM (72.9 kg) in your history on this lift.",
    ],
)
def test_a_lifts_own_best_is_not_a_ranking(stall, text: str) -> None:
    assert _comparisons(stall, LAT, text).passed


def test_a_ranking_against_the_other_lifts_is_still_checked(stall) -> None:
    assert not _comparisons(stall, LAT, "The strongest gain of all six lifts this week.").passed


def test_a_superlative_of_a_fall_is_ranked_by_the_fall(deload, quiet) -> None:
    assert _comparisons(deload, DEADLIFT, "The largest four-week e1RM decline at 12.1%.").passed
    assert not _comparisons(deload, SQUAT, "The largest four-week e1RM decline at 10.9%.").passed
    assert _comparisons(deload, ROW, "The smallest e1RM drop over four weeks at -2.7%.").passed
    # A real error from the stored runs: the second-largest gain called the smallest.
    smallest = "It posted the smallest four-week e1RM gain at 10.0%."
    assert not _comparisons(quiet, OHP, smallest, section="suggestions").passed


# --- universal claims: read the qualifier, the number and the direction --------------------


@pytest.mark.parametrize(
    "text",
    [
        "Strong week with nearly all lifts progressing.",
        "All five exercises that are progressing showed e1RM gains over four weeks.",
        "All six exercises increased or held volume this week.",
        "Keep the approach on all other lifts, which show steady gains.",
        "Consistent effort across the board at RPE 8.5.",
        "Mean RPE of 8.5 across the board.",
    ],
)
def test_qualified_or_effort_universals_pass_when_true(stall, text: str) -> None:
    assert _comparisons(stall, "Overall", text).passed, text


@pytest.mark.parametrize(
    "text",
    [
        "Strong week across the board.",
        "Strong across-the-board progress this week.",
        "All six exercises improved over four weeks.",
    ],
)
def test_unqualified_universals_still_need_every_lift_up(stall, quiet, text: str) -> None:
    assert not _comparisons(stall, "Overall", text).passed, text
    assert _comparisons(quiet, "Overall", text).passed, text  # every lift rose here


def test_effort_mentioned_after_a_progress_claim_does_not_excuse_it(stall) -> None:
    claim = "Every lift improved over four weeks, RPE steady at 8.5."
    assert not _comparisons(stall, "Overall", claim).passed
    assert _comparisons(stall, "Overall", "All six exercises were trained at higher RPE.").passed


def test_nearly_all_needs_most_lifts_up(deload) -> None:
    assert not _comparisons(deload, "Overall", "Nearly all lifts progressing.").passed


def test_a_fall_across_the_board_is_checked_against_falls(deload, stall) -> None:
    text = "Deload week with all lifts reduced and loads backed off across the board."
    assert _comparisons(deload, "Overall", text).passed
    assert not _comparisons(stall, "Overall", text).passed


def test_known_limit_a_universal_scoped_to_a_group_is_read_as_all_lifts(stall) -> None:
    # Pinned (docs/checks.md): "the upper-body lifts" is not recognised as a subset.
    text = "The upper-body lifts are progressing across the board."
    assert not _comparisons(stall, "Overall", text).passed


# --- deload, percentage ranges, thousands separators ----------------------------------------


def test_a_suggested_deload_inside_a_concern_is_advice(stall) -> None:
    advice = Finding(exercise=BENCH, text="Unchanged for five weeks; a brief deload may help.")
    assert _check(stall, advice, "concerns")["deload_grounded"].passed
    consider = Finding(exercise=BENCH, text="Unchanged for five weeks. Consider a deload.")
    assert _check(stall, consider, "concerns")["deload_grounded"].passed
    claim = Finding(exercise=BENCH, text="This was a deload week for the bench.")
    assert not _check(stall, claim, "concerns")["deload_grounded"].passed


@pytest.mark.parametrize("text", ["e1RM rose 4-9% on four lifts.", "e1RM rose 4–9% on four lifts."])
def test_a_rounded_range_is_not_a_quoted_figure(stall, text: str) -> None:
    assert _check(stall, Finding(exercise="Overall", text=text))["pct_grounded"].passed


def test_a_percentage_outside_a_range_is_still_checked(stall) -> None:
    result = _check(stall, Finding(exercise="Overall", text="e1RM rose 42% this month."))
    assert not result["pct_grounded"].passed


def test_kilograms_with_a_thousands_separator_are_read_whole(stall) -> None:
    grounded = Finding(exercise=SQUAT, text="Volume reached 3,450 kg this week.")
    assert _check(stall, grounded)["kg_grounded"].passed
    invented = Finding(exercise="Overall", text="Volume totalled 10,912.5 kg this week.")
    result = _check(stall, invented)["kg_grounded"]
    assert not result.passed and "10912.5" in result.detail
