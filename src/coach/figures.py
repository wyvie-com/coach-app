"""Every number the review may mention, computed here and nowhere else.

Pure functions from a list of ``Workout`` to Pydantic models, so the output can be
rendered as JSON for the model's user turn and validated against later. Rules:

- Volume: sum of weight times reps over working sets with both present.
- Top set: the heaviest working set; ties go to more reps, then to the higher RPE
  (the harder set is the more informative one).
- Estimated one-rep max: Epley, ``weight * (1 + reps / 30)``, over working sets,
  the week's best. A single rep is its own max.
- Mean RPE: mean over working sets that recorded one.
- Sessions baseline: mean sessions per week over the four weeks before the review
  week, counting an empty week as zero but never counting weeks before the first
  workout in the data. None when there is no prior data.
- Four-week change: this week's e1RM against the week four weeks earlier, or the
  earliest week in that window with data if that exact week is empty.
- History: one entry per week in the window, empty weeks included, so a stall and
  a gap look different.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from statistics import mean

from pydantic import BaseModel, ConfigDict

from coach.model import MELBOURNE, Exercise, Set, WeekId, Workout

MAX_HISTORY_WEEKS = 12
BASELINE_WEEKS = 4
TITLE_LIMIT = 60


class UnknownExerciseError(LookupError):
    """The requested exercise is not in the data. The message lists the names that are."""


def epley(weight_kg: float, reps: int) -> float:
    """Epley's estimate of a one-rep max. A single rep is taken as its own max, not 103 percent."""
    if reps <= 1:
        return weight_kg
    return weight_kg * (1 + reps / 30)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class TopSet(_Frozen):
    """The heaviest working set of the week for one exercise."""

    weight_kg: float
    reps: int
    rpe: float | None


class ExerciseFigures(_Frozen):
    """One exercise's week."""

    exercise: str
    template_id: str
    sessions: int
    working_sets: int
    warmup_sets: int
    other_sets: int
    volume_kg: float
    top_set: TopSet | None
    e1rm_kg: float | None
    mean_rpe: float | None
    superset: bool
    e1rm_change_4w_kg: float | None
    e1rm_change_4w_pct: float | None


class WeekFigures(_Frozen):
    """Everything the review is given about one week."""

    week: str
    zone: str
    sessions: int
    baseline_sessions: float | None
    sessions_missed: float | None
    session_titles: list[str]
    exercises: list[ExerciseFigures]
    warnings: list[str]


class HistoryEntry(_Frozen):
    """One week of one exercise, as the ``exercise_history`` tool returns it."""

    week: str
    sessions: int
    working_sets: int
    top_set_kg: float | None
    top_set_reps: int | None
    e1rm_kg: float | None
    mean_rpe: float | None


class ExerciseHistory(_Frozen):
    """A window of weeks for one exercise plus first-to-last changes."""

    exercise: str
    template_id: str
    weeks: list[HistoryEntry]
    e1rm_change_kg: float | None
    e1rm_change_pct: float | None
    rpe_change: float | None


def _working(exercises: Iterable[Exercise]) -> list[Set]:
    return [s for e in exercises for s in e.sets if s.is_working]


def _top_set(sets: Sequence[Set]) -> Set | None:
    loaded = [s for s in sets if s.weight_kg is not None and s.reps is not None]
    if not loaded:
        return None
    return max(loaded, key=lambda s: (s.weight_kg, s.reps, s.rpe if s.rpe is not None else -1.0))


def _e1rm(sets: Sequence[Set]) -> float | None:
    values = [epley(s.weight_kg, s.reps) for s in sets if s.weight_kg is not None and s.reps]
    return max(values) if values else None


def _mean_rpe(sets: Sequence[Set]) -> float | None:
    values = [s.rpe for s in sets if s.rpe is not None]
    return mean(values) if values else None


def _round(value: float | None, places: int = 1) -> float | None:
    return None if value is None else round(value, places)


def _pct(now: float | None, then: float | None) -> float | None:
    if now is None or then is None or then == 0:
        return None
    return 100 * (now / then - 1)


def _latest_titles(workouts: Sequence[Workout]) -> dict[str, str]:
    """The most recent title seen for each template id (titles can be edited in Hevy)."""
    titles: dict[str, str] = {}
    for workout in sorted(workouts, key=lambda w: w.start):
        for exercise in workout.exercises:
            titles[exercise.template_id] = exercise.title
    return titles


def _by_week(workouts: Sequence[Workout]) -> dict[WeekId, list[Workout]]:
    grouped: dict[WeekId, list[Workout]] = defaultdict(list)
    for workout in workouts:
        grouped[workout.week].append(workout)
    return grouped


def _exercises_in(workouts: Iterable[Workout], template_id: str) -> list[Exercise]:
    return [e for w in workouts for e in w.exercises if e.template_id == template_id]


def _week_e1rm(workouts: Sequence[Workout], template_id: str) -> float | None:
    return _e1rm(_working(_exercises_in(workouts, template_id)))


def _baseline(by_week: dict[WeekId, list[Workout]], week: WeekId) -> float | None:
    if not by_week:
        return None
    first = min(by_week)
    prior = [week.shift(-n) for n in range(1, BASELINE_WEEKS + 1)]
    counted = [len(by_week.get(w, [])) for w in prior if first <= w < week]
    return mean(counted) if counted else None


def week_figures(workouts: Sequence[Workout], week: WeekId) -> WeekFigures:
    """Compute the review week's figures from every workout available."""
    by_week = _by_week(workouts)
    this_week = sorted(by_week.get(week, []), key=lambda w: w.start)
    titles = _latest_titles(workouts)

    exercises: list[ExerciseFigures] = []
    other_types: dict[str, int] = defaultdict(int)
    for template_id in sorted({e.template_id for w in this_week for e in w.exercises}):
        present = _exercises_in(this_week, template_id)
        sets = [s for e in present for s in e.sets]
        working = [s for s in sets if s.is_working]
        for s in working:
            if s.kind.value == "other":
                other_types[s.raw_type] += 1
        top = _top_set(working)
        now = _e1rm(working)
        then = _comparison_e1rm(by_week, week, template_id)
        exercises.append(
            ExerciseFigures(
                exercise=titles[template_id],
                template_id=template_id,
                sessions=sum(
                    1 for w in this_week if any(e.template_id == template_id for e in w.exercises)
                ),
                working_sets=len(working),
                warmup_sets=len(sets) - len(working),
                other_sets=sum(1 for s in working if s.kind.value == "other"),
                volume_kg=round(
                    sum(
                        s.weight_kg * s.reps for s in working if s.weight_kg is not None and s.reps
                    ),
                    1,
                ),
                top_set=None
                if top is None
                else TopSet(weight_kg=top.weight_kg, reps=top.reps, rpe=top.rpe),
                e1rm_kg=_round(now),
                mean_rpe=_round(_mean_rpe(working), 2),
                superset=any(e.superset for e in present),
                e1rm_change_4w_kg=_round(None if now is None or then is None else now - then),
                e1rm_change_4w_pct=_round(_pct(now, then)),
            )
        )
    exercises.sort(key=lambda e: (-e.volume_kg, e.exercise))

    baseline = _baseline(by_week, week)
    sessions = len(this_week)
    warnings = []
    if other_types:
        count = sum(other_types.values())
        noun, verb = ("set", "was") if count == 1 else ("sets", "were")
        warnings.append(
            f"{count} {noun} with an unrecognised type {verb} counted as 'other': "
            + ", ".join(sorted(other_types))
        )
    return WeekFigures(
        week=str(week),
        zone=str(MELBOURNE.key),
        sessions=sessions,
        baseline_sessions=_round(baseline, 2),
        sessions_missed=None if baseline is None else _round(max(0.0, baseline - sessions), 2),
        session_titles=[w.title[:TITLE_LIMIT] for w in this_week],
        exercises=exercises,
        warnings=warnings,
    )


def _comparison_e1rm(
    by_week: dict[WeekId, list[Workout]], week: WeekId, template_id: str
) -> float | None:
    """The e1RM four weeks before ``week``, or the earliest week in that window with data."""
    exact = _week_e1rm(by_week.get(week.shift(-BASELINE_WEEKS), []), template_id)
    if exact is not None:
        return exact
    for back in range(BASELINE_WEEKS - 1, 0, -1):
        value = _week_e1rm(by_week.get(week.shift(-back), []), template_id)
        if value is not None:
            return value
    return None


def known_exercises(workouts: Sequence[Workout]) -> list[str]:
    """Display names of every exercise in the data, sorted."""
    return sorted(set(_latest_titles(workouts).values()))


def resolve_exercise(workouts: Sequence[Workout], name: str) -> tuple[str, str]:
    """Map a name from the figures (or a template id) to ``(display_title, template_id)``."""
    titles = _latest_titles(workouts)
    by_title = {title: template for template, title in titles.items()}
    if name in by_title:
        return name, by_title[name]
    folded = {title.casefold(): title for title in by_title}
    if name.casefold() in folded:
        title = folded[name.casefold()]
        return title, by_title[title]
    if name in titles:
        return titles[name], name
    raise UnknownExerciseError(
        f"Unknown exercise {name!r}. Known exercises: {', '.join(sorted(by_title))}"
    )


def exercise_history(
    workouts: Sequence[Workout], exercise: str, *, weeks: int, ending: WeekId
) -> ExerciseHistory:
    """One entry per week for the ``weeks`` weeks ending at ``ending``, oldest first."""
    if not 1 <= weeks <= MAX_HISTORY_WEEKS:
        raise ValueError(f"weeks must be 1..{MAX_HISTORY_WEEKS}, got {weeks}")
    title, template_id = resolve_exercise(workouts, exercise)
    by_week = _by_week(workouts)
    entries: list[HistoryEntry] = []
    for back in range(weeks - 1, -1, -1):
        week = ending.shift(-back)
        present = by_week.get(week, [])
        working = _working(_exercises_in(present, template_id))
        top = _top_set(working)
        entries.append(
            HistoryEntry(
                week=str(week),
                sessions=sum(
                    1 for w in present if any(e.template_id == template_id for e in w.exercises)
                ),
                working_sets=len(working),
                top_set_kg=None if top is None else top.weight_kg,
                top_set_reps=None if top is None else top.reps,
                e1rm_kg=_round(_e1rm(working)),
                mean_rpe=_round(_mean_rpe(working), 2),
            )
        )
    with_data = [e for e in entries if e.e1rm_kg is not None]
    first, last = (with_data[0], with_data[-1]) if len(with_data) >= 2 else (None, None)
    rpe_pair = [e.mean_rpe for e in with_data if e.mean_rpe is not None]
    return ExerciseHistory(
        exercise=title,
        template_id=template_id,
        weeks=entries,
        e1rm_change_kg=None if first is None else _round(last.e1rm_kg - first.e1rm_kg),
        e1rm_change_pct=None if first is None else _round(_pct(last.e1rm_kg, first.e1rm_kg)),
        rpe_change=None if len(rpe_pair) < 2 else _round(rpe_pair[-1] - rpe_pair[0], 2),
    )


def format_table(figures: WeekFigures) -> str:
    """A fixed-width table for the terminal. The JSON beside it is the authoritative form."""
    lines = [
        f"week {figures.week}  sessions {figures.sessions}"
        + (
            ""
            if figures.baseline_sessions is None
            else f"  baseline {figures.baseline_sessions:.2f}  missed {figures.sessions_missed:.2f}"
        )
    ]
    header = (
        f"{'exercise':<32} {'sess':>4} {'sets':>4} {'volume':>8} "
        f"{'top set':>14} {'e1RM':>7} {'RPE':>5} {'4w e1RM':>9}"
    )
    lines += [header, "-" * len(header)]
    for e in figures.exercises:
        top = "-" if e.top_set is None else f"{e.top_set.weight_kg:g} x {e.top_set.reps}"
        e1rm = "-" if e.e1rm_kg is None else f"{e.e1rm_kg:.1f}"
        rpe = "-" if e.mean_rpe is None else f"{e.mean_rpe:.1f}"
        change = "-" if e.e1rm_change_4w_pct is None else f"{e.e1rm_change_4w_pct:+.1f}%"
        lines.append(
            f"{e.exercise[:32]:<32} {e.sessions:>4} {e.working_sets:>4} {e.volume_kg:>8.0f} "
            f"{top:>14} {e1rm:>7} {rpe:>5} {change:>9}"
        )
    lines += [f"warning: {w}" for w in figures.warnings]
    return "\n".join(lines)
