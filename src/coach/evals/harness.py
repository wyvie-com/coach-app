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

from pydantic import BaseModel, ConfigDict

from coach import credentials
from coach.evals.cases import Case, build_case
from coach.evals.checks import CHECK_NAMES, run_checks
from coach.evals.grader import RUBRIC, grade
from coach.figures import week_figures
from coach.pricing import normalise_model
from coach.review.client import ClaudeClient
from coach.review.loop import run_review


class CheckSummary(BaseModel):
    """Pass rate over all trials, and how many cases passed in every trial."""

    model_config = ConfigDict(frozen=True)
    passed: int
    total: int
    pass_rate: float
    stable_cases: int


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
    checks: dict[str, bool]
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


def _summarise(trials: list[TrialRecord], case_names: list[str]) -> ModelSummary:
    checks = {}
    for name in CHECK_NAMES:
        passed = sum(1 for t in trials if t.checks.get(name))
        stable = sum(
            1 for case in case_names if all(t.checks.get(name) for t in trials if t.case == case)
        )
        checks[name] = CheckSummary(
            passed=passed,
            total=len(trials),
            pass_rate=passed / len(trials) if trials else 0.0,
            stable_cases=stable,
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
        rubric=rubric,
        outcomes=dict(sorted(outcomes.items())),
        tool_calls_mean=sum(t.tool_calls for t in trials) / n,
        seconds_mean=sum(t.seconds for t in trials) / n,
        review_cost_mean_usd=review_cost / n,
        review_cost_usd=review_cost,
        grader_cost_usd=grader_cost,
        cost_total_usd=review_cost + grader_cost,
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
) -> EvalReport:
    """Run the suite and write trials.jsonl, report.json and report.md under out_dir."""
    from coach.evals.report import render_markdown  # local import: report imports this module

    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "trials.jsonl"
    built = [build_case(case) for case in cases]
    reports: list[ModelReport] = []
    for model in _order(models):
        client = review_client(model)
        records: list[TrialRecord] = []
        for data in built:
            figures = week_figures(data.workouts, data.review_week)
            for trial in range(1, trials + 1):
                started = time.perf_counter()
                run = run_review(client, model, figures, data.workouts)
                results = run_checks(data.case, figures, run, data.workouts)
                graded = (
                    grade(grader_client, grader_model, figures, run.review) if run.review else None
                )
                record = TrialRecord(
                    case=data.case.name,
                    trial=trial,
                    model=model,
                    outcome=run.outcome,
                    checks={r.name: r.passed for r in results},
                    check_details={r.name: r.detail for r in results if not r.passed},
                    grade_outcome=None if graded is None else graded.outcome,
                    scores=None if graded is None else graded.scores,
                    grade_reasons=None if graded is None else graded.reasons,
                    grader_thinking=None if graded is None else graded.thinking,
                    review=None if run.review is None else run.review.model_dump(mode="json"),
                    tool_call_log=[c.model_dump(mode="json") for c in run.tool_calls],
                    tool_calls=len(run.tool_calls),
                    tool_errors=sum(1 for c in run.tool_calls if c.is_error),
                    turns=run.turns,
                    seconds=time.perf_counter() - started,
                    review_cost_usd=run.cost.total_usd,
                    grader_cost_usd=0.0 if graded is None else graded.cost.total_usd,
                )
                records.append(record)
                with jsonl.open("a") as handle:
                    handle.write(record.model_dump_json() + "\n")
                failed = [n for n, ok in record.checks.items() if not ok]
                log(
                    f"{model} {record.case} t{trial}: {record.outcome}, "
                    f"{len(failed)} failed{' (' + ', '.join(failed) + ')' if failed else ''}, "
                    f"${record.review_cost_usd + record.grader_cost_usd:.4f}"
                )
        reports.append(
            ModelReport(
                model=model, summary=_summarise(records, [c.name for c in cases]), trials=records
            )
        )
    report = EvalReport(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        trials=trials,
        grader_model=grader_model,
        cases=[c.name for c in cases],
        models=reports,
        total_cost_usd=sum(r.summary.cost_total_usd for r in reports),
    )
    (out_dir / "report.json").write_text(report.model_dump_json(indent=2) + "\n")
    (out_dir / "report.md").write_text(render_markdown(report))
    return report
