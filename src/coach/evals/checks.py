"""Code checks over one review run. These run first; the rubric runs second.

Each check is a pure function of the case, the figures, the run record and the
workouts (used to recompute tool results, which the run record does not store). A
run without a review fails every check: a review that does not exist found nothing.

What each check can and cannot catch is written in docs/notes/slice-4.md.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from coach.evals.cases import Case
from coach.figures import UnknownExerciseError, WeekFigures, exercise_history
from coach.model import WeekId, Workout
from coach.review.loop import ReviewRun
from coach.review.schema import Review

CHECK_NAMES = (
    "schema_valid",
    "story_found",
    "no_false_alarm",
    "exercises_exist",
    "kg_grounded",
    "concern_preceded_by_tool",
    "max_three_suggestions",
    "sessions_threshold",
)
#: The checks that need no planted story, so they also run on a real week's review.
DATA_CHECK_NAMES = (
    "schema_valid",
    "exercises_exist",
    "kg_grounded",
    "concern_preceded_by_tool",
    "max_three_suggestions",
    "sessions_threshold",
)
KG_TOLERANCE = 0.5
_KG = re.compile(r"(\d+(?:\.\d+)?)\s*(?:kg|kilograms?)\b", re.IGNORECASE)
_SESSIONS = re.compile(r"\bsessions?\b", re.IGNORECASE)
#: Prompt rule 9: sessions missed is a concern only at this value or more.
SESSIONS_CONCERN_THRESHOLD = 1.0


class CheckResult(BaseModel):
    """One check's verdict with a one-line reason."""

    model_config = ConfigDict(frozen=True)

    name: str
    passed: bool
    detail: str


def _kg_values(payload: Any) -> set[float]:
    """Every number under a key that names kilograms, anywhere in a JSON-like structure."""
    found: set[float] = set()

    def walk(node: Any, key: str | None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)
        elif isinstance(node, int | float) and not isinstance(node, bool) and key and "kg" in key:
            found.add(abs(float(node)))

    walk(payload, None)
    return found


def _grounding_values(
    figures: WeekFigures,
    run: ReviewRun,
    workouts: Sequence[Workout],
    *,
    allow_differences: bool,
) -> set[float]:
    """Kilogram figures the review may quote.

    Each exercise's figures and each successful tool result contribute their own values.
    With ``allow_differences`` (the default since the first full eval run, see
    docs/findings.md), the absolute difference between two values of the same exercise
    counts too: "up 2.5 kg a fortnight" is arithmetic on the data, not an invention.
    Differences across exercises never count.
    """
    groups: list[set[float]] = [_kg_values(e.model_dump(mode="json")) for e in figures.exercises]
    ending = WeekId.parse(figures.week)
    for call in run.tool_calls:
        if call.is_error or call.weeks is None:
            continue
        try:
            history = exercise_history(workouts, call.exercise, weeks=call.weeks, ending=ending)
        except (UnknownExerciseError, ValueError):
            continue
        groups.append(_kg_values(history.model_dump(mode="json")))
    allowed: set[float] = set()
    for group in groups:
        allowed |= group
        if allow_differences:
            values = sorted(group)
            allowed |= {abs(a - b) for i, a in enumerate(values) for b in values[i + 1 :]}
    return allowed


def _section(review: Review, name: str):
    return getattr(review, name)


def _data_checks(
    review: Review,
    figures: WeekFigures,
    run: ReviewRun,
    workouts: Sequence[Workout],
    *,
    allow_differences: bool,
) -> list[CheckResult]:
    results = [CheckResult(name="schema_valid", passed=True, detail="outcome ok, Review validated")]

    known = {e.exercise for e in figures.exercises} | {"Overall"}
    unknown = sorted(
        {
            f.exercise
            for section in ("highlights", "concerns", "suggestions")
            for f in _section(review, section)
            if f.exercise not in known
        }
    )
    results.append(
        CheckResult(
            name="exercises_exist",
            passed=not unknown,
            detail="every name is in the figures"
            if not unknown
            else "unknown: " + ", ".join(unknown),
        )
    )

    allowed = _grounding_values(figures, run, workouts, allow_differences=allow_differences)
    texts = [review.headline] + [f.text for f in review.highlights + review.concerns]
    quoted = [float(m.group(1)) for text in texts for m in _KG.finditer(text)]
    ungrounded = [q for q in quoted if not any(abs(q - v) <= KG_TOLERANCE for v in allowed)]
    results.append(
        CheckResult(
            name="kg_grounded",
            passed=not ungrounded,
            detail=f"{len(quoted)} kg figures, all in the data or a tool result"
            if not ungrounded
            else "not in data or tool results: " + ", ".join(f"{q:g}" for q in ungrounded),
        )
    )

    called = {c.exercise.casefold() for c in run.tool_calls if not c.is_error}
    uncalled = [
        f.exercise
        for f in review.concerns
        if f.exercise != "Overall" and f.exercise.casefold() not in called
    ]
    results.append(
        CheckResult(
            name="concern_preceded_by_tool",
            passed=not uncalled,
            detail="every exercise concern had a tool call"
            if not uncalled
            else "no successful tool call for: " + ", ".join(uncalled),
        )
    )

    results.append(
        CheckResult(
            name="max_three_suggestions",
            passed=len(review.suggestions) <= 3,
            detail=f"{len(review.suggestions)} suggestions",
        )
    )

    # Added from a real failure (docs/findings.md): 0.75 of a missed session raised as a concern.
    missed = figures.sessions_missed or 0.0
    session_concerns = [
        f for f in review.concerns if f.exercise == "Overall" and _SESSIONS.search(f.text)
    ]
    premature = session_concerns and missed < SESSIONS_CONCERN_THRESHOLD
    results.append(
        CheckResult(
            name="sessions_threshold",
            passed=not premature,
            detail=(
                f"Overall sessions concern with sessions_missed {missed:.2f} < "
                f"{SESSIONS_CONCERN_THRESHOLD:.1f}"
                if premature
                else f"sessions_missed {missed:.2f}; "
                + ("sessions concern justified" if session_concerns else "no sessions concern")
            ),
        )
    )
    return results


def _story_checks(case: Case, review: Review) -> list[CheckResult]:
    missing = []
    for expectation in case.expected:
        findings = _section(review, expectation.section)
        hit = any(
            expectation.exercise == "any" or f.exercise == expectation.exercise for f in findings
        )
        if not hit:
            missing.append(f"{expectation.exercise} in {expectation.section}")
    planted = {e.exercise for e in case.expected if e.section == "concerns"}
    alarms = [f.exercise for f in review.concerns if f.exercise not in planted]
    return [
        CheckResult(
            name="story_found",
            passed=not missing,
            detail="all expected findings present"
            if not missing
            else "missing: " + "; ".join(missing),
        ),
        CheckResult(
            name="no_false_alarm",
            passed=not alarms,
            detail="no unplanted concern"
            if not alarms
            else "unplanted concerns: " + ", ".join(alarms),
        ),
    ]


def _no_review(names: Sequence[str], run: ReviewRun) -> list[CheckResult]:
    detail = f"no review: outcome {run.outcome}" + (f" ({run.error})" if run.error else "")
    return [CheckResult(name=name, passed=False, detail=detail) for name in names]


def run_checks(
    case: Case,
    figures: WeekFigures,
    run: ReviewRun,
    workouts: Sequence[Workout],
    *,
    allow_differences: bool = True,
) -> list[CheckResult]:
    """Run every check in CHECK_NAMES order."""
    if run.review is None:
        return _no_review(CHECK_NAMES, run)
    data = _data_checks(run.review, figures, run, workouts, allow_differences=allow_differences)
    story = _story_checks(case, run.review)
    by_name = {r.name: r for r in data + story}
    return [by_name[name] for name in CHECK_NAMES]


def run_data_checks(
    figures: WeekFigures,
    run: ReviewRun,
    workouts: Sequence[Workout],
    *,
    allow_differences: bool = True,
) -> list[CheckResult]:
    """The checks that apply to a real week, where nothing was planted."""
    if run.review is None:
        return _no_review(DATA_CHECK_NAMES, run)
    return _data_checks(run.review, figures, run, workouts, allow_differences=allow_differences)
