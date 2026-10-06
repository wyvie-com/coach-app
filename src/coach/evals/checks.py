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
    "comparisons_grounded",
    "flags_in_concerns",
    "pct_grounded",
    "deload_grounded",
)
#: The checks that need no planted story, so they also run on a real week's review.
DATA_CHECK_NAMES = (
    "schema_valid",
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
KG_TOLERANCE = 0.5
_KG = re.compile(r"(\d+(?:\.\d+)?)\s*(?:kg|kilograms?)\b", re.IGNORECASE)
_SESSIONS = re.compile(r"\bsessions?\b", re.IGNORECASE)
_PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:%|percent\b|pct\b)", re.IGNORECASE)
PCT_TOLERANCE = 0.05
_DELOAD = re.compile(r"\bdeload", re.IGNORECASE)
#: Words that rank one exercise against the others. "highest" and "best" are left out because
#: they usually compare one exercise with its own history, which this check cannot judge.
_SUPERLATIVE = re.compile(
    r"\b(fastest|largest|biggest|strongest|greatest|slowest|smallest|weakest)\b", re.IGNORECASE
)
_UNIVERSAL = re.compile(
    r"\b(?:all|every)\s+(?:\w+\s+)?(?:exercises?|lifts?|movements?)\b.{0,60}?"
    r"\b(?:improv|increas|rose|rising|progress|gain|grew|growth|advanc|higher|up)\w*"
    r"|across the board",
    re.IGNORECASE,
)
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
    results.append(_comparisons_check(review, figures))
    results.append(_flags_check(review, figures))
    results.append(_pct_check(review, figures, run, workouts))
    results.append(_deload_check(review, figures))
    return results


def _flags_check(review: Review, figures: WeekFigures) -> CheckResult:
    """Every flag the code raised must appear in concerns under its exercise.

    Added after the fourth full run (docs/findings.md entry 11), where the two planted stories
    the model missed were both figures it had been given and chose to read kindly: a one-session
    week called a deload, a five-week stall called "held steady". The flags take that choice away.
    """
    named = {f.exercise for f in review.concerns}
    missing = [flag.text for flag in figures.summary.flags if flag.exercise not in named]
    return CheckResult(
        name="flags_in_concerns",
        passed=not missing,
        detail=f"{len(figures.summary.flags)} flags, all in concerns"
        if not missing
        else "flags not in concerns: " + "; ".join(missing),
    )


def _pct_values(payload: Any) -> set[float]:
    """Every number under a key that names a percentage, anywhere in a JSON-like structure."""
    found: set[float] = set()

    def walk(node: Any, key: str | None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)
        elif isinstance(node, int | float) and not isinstance(node, bool) and key and "pct" in key:
            found.add(float(node))

    walk(payload, None)
    return found


def _pct_check(
    review: Review, figures: WeekFigures, run: ReviewRun, workouts: Sequence[Workout]
) -> CheckResult:
    """A percentage in a finding about one exercise must be that exercise's own figure.

    From the figures or from a tool result for it; "Overall" findings and the headline may
    quote any exercise's.

    The kilogram check is global because loads repeat across lifts; percentages do not, and the
    Sonnet grader found them moved between lifts three times (docs/findings.md entry 10).
    """
    per_exercise: dict[str, set[float]] = {
        e.exercise: _pct_values(e.model_dump(mode="json")) for e in figures.exercises
    }
    ending = WeekId.parse(figures.week)
    for call in run.tool_calls:
        if call.is_error or call.weeks is None:
            continue
        try:
            history = exercise_history(workouts, call.exercise, weeks=call.weeks, ending=ending)
        except (UnknownExerciseError, ValueError):
            continue
        per_exercise.setdefault(history.exercise, set()).update(
            _pct_values(history.model_dump(mode="json"))
        )
    everything = set().union(*per_exercise.values()) if per_exercise else set()
    bad: list[str] = []
    findings = [("Overall", review.headline)] + [
        (f.exercise, f.text) for f in review.highlights + review.concerns
    ]
    for exercise, text in findings:
        allowed = everything if exercise == "Overall" else per_exercise.get(exercise, set())
        for match in _PCT.finditer(text):
            quoted = float(match.group(1))
            if not any(abs(quoted - v) <= PCT_TOLERANCE for v in allowed):
                where = "any exercise" if exercise == "Overall" else exercise
                bad.append(f"{quoted:g}% not a figure of {where}")
    return CheckResult(
        name="pct_grounded",
        passed=not bad,
        detail="every percentage belongs to the exercise it is quoted for"
        if not bad
        else "; ".join(bad),
    )


def _deload_check(review: Review, figures: WeekFigures) -> CheckResult:
    """The week may be called a deload only when a session title says so (rule 8, summary.deload).

    Suggestions are not checked: "consider a deload" is advice, not a claim about the week.
    Rescoring the fourth full run showed 7 of 8 mentions were exactly that.
    """
    texts = [review.headline] + [f.text for f in review.highlights + review.concerns]
    said = any(_DELOAD.search(t) for t in texts)
    unfounded = said and not figures.summary.deload
    return CheckResult(
        name="deload_grounded",
        passed=not unfounded,
        detail="deload called with no Deload session title"
        if unfounded
        else ("deload week, titled" if figures.summary.deload else "no deload claim"),
    )


def _comparisons_check(review: Review, figures: WeekFigures) -> CheckResult:
    """A ranking of exercises must match ``leaders``; "all" or "every" must match ``counts``.

    Added after the Sonnet grader found a wrong "fastest" or "largest" in 5 of 16 reviews
    (docs/findings.md). A finding about one exercise may use a superlative only when that
    exercise leads on some figure; an "Overall" finding must name a leader in its text.
    A universal claim of progress passes only when every exercise rose on e1RM or on volume.
    """
    leaders = {name for name in figures.leaders.model_dump().values() if name}
    counts = figures.counts
    offences: list[str] = []
    findings = [("Overall", review.headline)] + [
        (f.exercise, f.text) for f in review.highlights + review.concerns + review.suggestions
    ]
    for exercise, text in findings:
        for match in _SUPERLATIVE.finditer(text):
            supported = (
                exercise in leaders
                if exercise != "Overall"
                else any(name in text for name in leaders)
            )
            if not supported:
                offences.append(f"{exercise}: '{match.group(0)}' not backed by leaders")
        if exercise in leaders:
            continue  # "led all exercises" by the exercise that does lead is a ranking, not a claim
        for match in _UNIVERSAL.finditer(text):
            full = counts.exercises > 0 and counts.exercises in (
                counts.e1rm_up_4w,
                counts.volume_up_1w,
            )
            if not full:
                offences.append(f"{exercise}: '{match.group(0)}' against counts")
    return CheckResult(
        name="comparisons_grounded",
        passed=not offences,
        detail="rankings match leaders and counts" if not offences else "; ".join(offences),
    )


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
