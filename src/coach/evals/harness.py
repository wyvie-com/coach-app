"""Run every case, several trials, one or more models; checks first, rubric second.

Each trial is appended to ``trials.jsonl`` as soon as it finishes, so a crash or a
rate limit halfway through a paid run loses nothing that was already bought. The
report is assembled at the end. Haiku always comes first in the report because it
is the default the other models are compared against.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
from pydantic import BaseModel, ConfigDict

from coach import credentials
from coach.evals.batch import BatchRunner, run_trials_batched
from coach.evals.cases import BuiltCase, Case, build_case
from coach.evals.checks import CHECK_NAMES, run_checks
from coach.evals.grader import RUBRIC, GradeResult, grade, histories_for
from coach.figures import week_figures
from coach.pricing import normalise_model
from coach.review.client import ClaudeClient
from coach.review.loop import ReviewRun, run_review


class CheckSummary(BaseModel):
    """Pass rate over the trials a check applied to, and how many cases passed in every trial.

    ``total`` and ``cases`` count only trials and cases the check could test; trials where it
    had nothing to test are in ``not_applicable``, never in the pass rate.
    """

    model_config = ConfigDict(frozen=True)
    passed: int
    total: int
    pass_rate: float
    stable_cases: int
    not_applicable: int = 0
    cases: int = 0


class RubricSummary(BaseModel):
    """Mean and spread of one rubric dimension over graded trials."""

    model_config = ConfigDict(frozen=True)
    mean: float
    std: float
    min: int
    max: int
    n: int


class ModelSummary(BaseModel):
    """The summary table's column for one model."""

    model_config = ConfigDict(frozen=True)
    checks: dict[str, CheckSummary]
    #: ``no_false_alarm`` on the negative cases alone, the result for weeks with nothing planted.
    negative_cases: CheckSummary | None = None
    rubric: dict[str, RubricSummary]
    outcomes: dict[str, int]
    tool_calls_mean: float
    seconds_mean: float
    review_cost_mean_usd: float
    review_cost_usd: float
    grader_cost_usd: float
    cost_total_usd: float


class TrialRecord(BaseModel):
    """One case, one trial, one model."""

    model_config = ConfigDict(frozen=True)
    case: str
    trial: int
    model: str
    outcome: str
    #: True pass, False fail, None not applicable (the check had nothing to test).
    checks: dict[str, bool | None]
    check_details: dict[str, str]
    grade_outcome: str | None
    scores: dict[str, int] | None
    grade_reasons: dict[str, str] | None
    grader_thinking: str | None
    #: The review itself, so a changed check can re-score a past run without paying again.
    review: dict[str, Any] | None
    tool_call_log: list[dict[str, Any]]
    tool_calls: int
    tool_errors: int
    turns: int
    seconds: float
    review_cost_usd: float
    grader_cost_usd: float


class ModelReport(BaseModel):
    """Summary plus every trial for one model."""

    model_config = ConfigDict(frozen=True)
    model: str
    summary: ModelSummary
    trials: list[TrialRecord]


class EvalReport(BaseModel):
    """The whole run."""

    model_config = ConfigDict(frozen=True)
    created_at: str
    trials: int
    grader_model: str
    cases: list[str]
    models: list[ModelReport]
    total_cost_usd: float
    #: Set when an API error ended the run before every trial ran; the report covers what ran.
    stopped_early: str | None = None
    #: "live" for one request at a time; "batch" for the Message Batches API at half price.
    mode: str = "live"
    #: Batch ids, so results can be fetched again from the API for 29 days.
    batch_ids: list[str] = []


#: Mean cost of one trial (review plus Haiku grading) on the 2026-10-05 runs; for estimates only.
USD_PER_TRIAL_ESTIMATE = 0.045


def estimate_usd(*, cases: int, trials: int, models: int) -> float:
    """A rough spend estimate to print before a paid run starts."""
    return cases * trials * models * USD_PER_TRIAL_ESTIMATE


def ensure_credentials(client: ClaudeClient) -> None:
    """Refuse to start a paid run unless the Anthropic route answers 200."""
    result = credentials.check_anthropic(client)  # type: ignore[arg-type]
    if not result.ok:
        raise RuntimeError(
            f"Anthropic credential check failed: status {result.status} ({result.detail})"
        )


def _order(models: Sequence[str]) -> list[str]:
    haiku = [m for m in models if normalise_model(m).startswith("claude-haiku")]
    rest = [m for m in models if m not in haiku]
    return list(dict.fromkeys(haiku + rest))


def _check_summary(trials: list[TrialRecord], name: str, case_names: list[str]) -> CheckSummary:
    tested = [t for t in trials if t.checks.get(name) is not None]
    passed = sum(1 for t in tested if t.checks[name])
    tested_cases = [case for case in case_names if any(t.case == case for t in tested)]
    stable = sum(
        1 for case in tested_cases if all(t.checks[name] for t in tested if t.case == case)
    )
    return CheckSummary(
        passed=passed,
        total=len(tested),
        pass_rate=passed / len(tested) if tested else 0.0,
        stable_cases=stable,
        not_applicable=len(trials) - len(tested),
        cases=len(tested_cases),
    )


def _summarise(
    trials: list[TrialRecord], case_names: list[str], negative_cases: frozenset[str] = frozenset()
) -> ModelSummary:
    checks = {name: _check_summary(trials, name, case_names) for name in CHECK_NAMES}
    negatives = [t for t in trials if t.case in negative_cases]
    negative_summary = (
        _check_summary(negatives, "no_false_alarm", [c for c in case_names if c in negative_cases])
        if negatives
        else None
    )
    rubric = {}
    for dim in RUBRIC:
        values = [t.scores[dim] for t in trials if t.scores]
        if values:
            rubric[dim] = RubricSummary(
                mean=statistics.fmean(values),
                std=statistics.pstdev(values) if len(values) > 1 else 0.0,
                min=min(values),
                max=max(values),
                n=len(values),
            )
    outcomes: dict[str, int] = {}
    for t in trials:
        outcomes[t.outcome] = outcomes.get(t.outcome, 0) + 1
    review_cost = sum(t.review_cost_usd for t in trials)
    grader_cost = sum(t.grader_cost_usd for t in trials)
    n = len(trials) or 1
    return ModelSummary(
        checks=checks,
        negative_cases=negative_summary,
        rubric=rubric,
        outcomes=dict(sorted(outcomes.items())),
        tool_calls_mean=sum(t.tool_calls for t in trials) / n,
        seconds_mean=sum(t.seconds for t in trials) / n,
        review_cost_mean_usd=review_cost / n,
        review_cost_usd=review_cost,
        grader_cost_usd=grader_cost,
        cost_total_usd=review_cost + grader_cost,
    )


def _record(
    data: BuiltCase,
    trial: int,
    model: str,
    run: ReviewRun,
    results,
    graded: GradeResult | None,
    seconds: float,
) -> TrialRecord:
    return TrialRecord(
        case=data.case.name,
        trial=trial,
        model=model,
        outcome=run.outcome,
        checks={r.name: r.passed if r.applicable else None for r in results},
        check_details={r.name: r.detail for r in results if r.applicable and not r.passed},
        grade_outcome=None if graded is None else graded.outcome,
        scores=None if graded is None else graded.scores,
        grade_reasons=None if graded is None else graded.reasons,
        grader_thinking=None if graded is None else graded.thinking,
        review=None if run.review is None else run.review.model_dump(mode="json"),
        tool_call_log=[c.model_dump(mode="json") for c in run.tool_calls],
        tool_calls=len(run.tool_calls),
        tool_errors=sum(1 for c in run.tool_calls if c.is_error),
        turns=run.turns,
        seconds=seconds,
        review_cost_usd=run.cost.total_usd,
        grader_cost_usd=0.0 if graded is None else graded.cost.total_usd,
    )


def _api_error_record(
    case: str, trial: int, model: str, detail: str, seconds: float
) -> TrialRecord:
    """A trial that never got a review because the request itself failed."""
    return TrialRecord(
        case=case,
        trial=trial,
        model=model,
        outcome="api_error",
        checks=dict.fromkeys(CHECK_NAMES, False),
        check_details=dict.fromkeys(CHECK_NAMES, detail),
        grade_outcome=None,
        scores=None,
        grade_reasons=None,
        grader_thinking=None,
        review=None,
        tool_call_log=[],
        tool_calls=0,
        tool_errors=0,
        turns=0,
        seconds=seconds,
        review_cost_usd=0.0,
        grader_cost_usd=0.0,
    )


def _append(jsonl: Path, record: TrialRecord) -> None:
    with jsonl.open("a") as handle:
        handle.write(record.model_dump_json() + "\n")


def _describe(record: TrialRecord, spent: float) -> str:
    failed = [n for n, ok in record.checks.items() if ok is False]
    return (
        f"{record.model} {record.case} t{record.trial}: {record.outcome}, "
        f"{len(failed)} failed{' (' + ', '.join(failed) + ')' if failed else ''}, "
        f"${record.review_cost_usd + record.grader_cost_usd:.4f} (run ${spent:.2f})"
    )


def run_eval(
    *,
    cases: Sequence[Case],
    models: Sequence[str],
    trials: int,
    review_client: Callable[[str], ClaudeClient],
    grader_client: ClaudeClient,
    grader_model: str,
    out_dir: Path,
    log: Callable[[str], None] = lambda _: None,
    budget_usd: float | None = None,
    batch: BatchRunner | None = None,
) -> EvalReport:
    """Run the suite and write trials.jsonl, report.json and report.md under out_dir.

    ``budget_usd`` stops the run, after the trial that crosses it, so an estimate that
    was wrong costs one trial rather than the rest of the run. With ``batch`` the whole
    model's trials go through the Message Batches API in rounds; a batch cannot be
    stopped part-way, so there the cap is checked between models only.
    """
    from coach.evals.report import render_markdown  # local import: report imports this module

    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "trials.jsonl"
    built = [build_case(case) for case in cases]
    reports: list[ModelReport] = []
    stopped_early: str | None = None
    spent = 0.0
    negative = frozenset(c.name for c in cases if not c.expected)
    for model in _order(models):
        if stopped_early:
            break
        records: list[TrialRecord] = []
        if batch is not None:
            records, spent, stopped_early = _run_model_batched(
                batch, model, built, trials, grader_model, jsonl, log, spent, budget_usd
            )
            reports.append(
                ModelReport(
                    model=model,
                    summary=_summarise(records, [c.name for c in cases], negative),
                    trials=records,
                )
            )
            continue
        client = review_client(model)
        for data in built:
            if stopped_early:
                break
            figures = week_figures(data.workouts, data.review_week)
            for trial in range(1, trials + 1):
                started = time.perf_counter()
                try:
                    run = run_review(client, model, figures, data.workouts)
                    results = run_checks(data.case, figures, run, data.workouts)
                    graded = (
                        grade(
                            grader_client,
                            grader_model,
                            figures,
                            run.review,
                            histories_for(run.tool_calls, data.workouts, figures.week),
                        )
                        if run.review
                        else None
                    )
                except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                    # Billing, auth, outage: record it as a trial so the paid work is kept, then
                    # stop. Continuing would fail every remaining trial the same way.
                    stopped_early = f"{model} {data.case.name} trial {trial}: {type(exc).__name__}"
                    record = _api_error_record(
                        data.case.name,
                        trial,
                        model,
                        f"api error: {exc}",
                        time.perf_counter() - started,
                    )
                    records.append(record)
                    _append(jsonl, record)
                    log(f"{stopped_early}; stopping. {exc}")
                    break
                record = _record(
                    data, trial, model, run, results, graded, time.perf_counter() - started
                )
                records.append(record)
                _append(jsonl, record)
                spent += record.review_cost_usd + record.grader_cost_usd
                log(_describe(record, spent))
                if budget_usd is not None and spent > budget_usd:
                    stopped_early = (
                        f"{model} {data.case.name} trial {trial}: budget ${budget_usd:.2f} "
                        f"exceeded (${spent:.2f})"
                    )
                    log(f"{stopped_early}; stopping.")
                    break
        reports.append(
            ModelReport(
                model=model,
                summary=_summarise(records, [c.name for c in cases], negative),
                trials=records,
            )
        )
    report = EvalReport(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        trials=trials,
        grader_model=grader_model,
        cases=[c.name for c in cases],
        models=reports,
        total_cost_usd=sum(r.summary.cost_total_usd for r in reports),
        stopped_early=stopped_early,
        mode="batch" if batch is not None else "live",
        batch_ids=[] if batch is None else list(batch.batch_ids),
    )
    (out_dir / "report.json").write_text(report.model_dump_json(indent=2) + "\n")
    (out_dir / "report.md").write_text(render_markdown(report))
    return report


def _run_model_batched(
    batch: BatchRunner,
    model: str,
    built: Sequence[BuiltCase],
    trials: int,
    grader_model: str,
    jsonl: Path,
    log: Callable[[str], None],
    spent: float,
    budget_usd: float | None,
) -> tuple[list[TrialRecord], float, str | None]:
    """One model's trials through batches. Records are written once the batches end."""
    started = time.perf_counter()
    records: list[TrialRecord] = []
    try:
        done = run_trials_batched(
            batch, model=model, built=built, trials=trials, grader_model=grader_model, log=log
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        # Nothing was bought that the API will not keep: a submitted batch's results stay
        # readable by id for 29 days, and the ids are logged as they are created.
        stopped = f"{model} batch: {type(exc).__name__}"
        for data in built:
            for trial in range(1, trials + 1):
                record = _api_error_record(data.case.name, trial, model, f"api error: {exc}", 0.0)
                records.append(record)
                _append(jsonl, record)
        log(f"{stopped}; stopping. {exc}")
        return records, spent, stopped
    elapsed = time.perf_counter() - started
    for item in done:
        results = run_checks(item.data.case, item.figures, item.run, item.data.workouts)
        record = _record(
            item.data, item.trial, model, item.run, results, item.graded, elapsed / len(done)
        )
        records.append(record)
        _append(jsonl, record)
        spent += record.review_cost_usd + record.grader_cost_usd
        log(_describe(record, spent))
    stopped = None
    if budget_usd is not None and spent > budget_usd:
        stopped = f"{model}: budget ${budget_usd:.2f} exceeded (${spent:.2f}) after its batches"
        log(f"{stopped}; no further model will run.")
    return records, spent, stopped
