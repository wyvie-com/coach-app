"""`coach review` writes review, figures, tool calls, usage and cost under out/<week>/."""

from __future__ import annotations

import json
from pathlib import Path

from coach.evals.cases import CASES, build_case
from coach.figures import week_figures
from coach.pricing import Cost
from coach.review.loop import RequestUsage, ReviewRun, ToolCall
from coach.review.output import write_run
from coach.review.schema import Finding, Review


def test_write_run_produces_the_five_files_and_no_secret(tmp_path: Path) -> None:
    data = build_case(next(c for c in CASES if c.name == "squat_pr-1"))
    figures = week_figures(data.workouts, data.review_week)
    review = Review(
        headline="Squat PR.",
        highlights=[Finding(exercise="Squat (Barbell)", text="New best at 135 kg x 5.")],
        concerns=[],
        suggestions=[],
    )
    run = ReviewRun(
        outcome="ok",
        model="claude-haiku-4-5-20251001",
        review=review,
        raw_text=review.model_dump_json(),
        turns=2,
        tool_calls=[
            ToolCall(exercise="Squat (Barbell)", weeks=12, is_error=False, result_chars=900)
        ],
        requests=[
            RequestUsage(
                model="claude-haiku-4-5-20251001",
                input_tokens=10,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                output_tokens=5,
                total_usd=0.0001,
            )
        ],
        cost=Cost(
            model="claude-haiku-4-5-20251001",
            input_usd=0.00001,
            cache_write_usd=0.0,
            cache_read_usd=0.0,
            output_usd=0.000025,
            total_usd=0.000035,
        ),
        seconds=1.5,
    )
    directory = write_run(tmp_path, figures, run)
    assert directory == tmp_path / "2026-W40"
    names = sorted(p.name for p in directory.iterdir())
    assert names == ["cost.json", "figures.json", "review.json", "review.md", "run.json"]
    assert json.loads((directory / "review.json").read_text())["headline"] == "Squat PR."
    assert json.loads((directory / "cost.json").read_text())["total_usd"] == 0.000035
    assert "Squat PR." in (directory / "review.md").read_text()
    blob = "".join(p.read_text() for p in directory.iterdir())
    assert "sk-ant" not in blob and "api-key" not in blob


def test_markdown_shows_a_check_with_nothing_to_test_as_not_applicable() -> None:
    from coach.evals.checks import run_data_checks
    from coach.review.output import render_markdown

    data = build_case(next(c for c in CASES if c.name == "squat_pr-1"))  # a week with no flags
    figures = week_figures(data.workouts, data.review_week)
    review = Review(
        headline="Squat PR.",
        highlights=[Finding(exercise="Squat (Barbell)", text="New best.")],
        concerns=[],
        suggestions=[],
    )
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
        seconds=0.1,
    )
    markdown = render_markdown(figures, run, run_data_checks(figures, run, data.workouts))
    assert "- flags_carried: n/a (no flags this week)" in markdown
    assert "- flags_consistent: n/a" in markdown
    assert "- schema_valid: pass" in markdown
