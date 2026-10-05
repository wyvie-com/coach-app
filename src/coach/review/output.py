"""Write a review run under ``out/<week>/``. Everything a run produced, nothing secret."""

from __future__ import annotations

import json
from pathlib import Path

from coach.figures import WeekFigures
from coach.review.loop import ReviewRun


def render_markdown(figures: WeekFigures, run: ReviewRun) -> str:
    """A readable version of the review, with the run's outcome and cost at the end."""
    lines = [f"# Review, ISO week {figures.week}", ""]
    if run.review is None:
        lines += [f"No review: outcome `{run.outcome}`.", ""]
        if run.error:
            lines += [f"Error: {run.error}", ""]
    else:
        review = run.review
        lines += [f"**{review.headline}**", ""]
        for title, items in (
            ("Highlights", review.highlights),
            ("Concerns", review.concerns),
            ("Suggestions", review.suggestions),
        ):
            lines.append(f"## {title}")
            lines += [f"- **{f.exercise}**: {f.text}" for f in items] or ["- none"]
            lines.append("")
    calls = ", ".join(
        f"{c.exercise} ({c.weeks}w{', error' if c.is_error else ''})" for c in run.tool_calls
    )
    lines += [
        "## Run",
        f"- model: {run.model}",
        f"- outcome: {run.outcome}",
        f"- turns: {run.turns}",
        f"- tool calls: {calls or 'none'}",
        f"- cost: ${run.cost.total_usd:.5f} (input ${run.cost.input_usd:.5f}, cache write "
        f"${run.cost.cache_write_usd:.5f}, cache read ${run.cost.cache_read_usd:.5f}, "
        f"output ${run.cost.output_usd:.5f})",
        f"- seconds: {run.seconds:.1f}",
    ]
    return "\n".join(lines) + "\n"


def write_run(out_root: Path, figures: WeekFigures, run: ReviewRun) -> Path:
    """Write figures, review, run record, cost and markdown. Returns the directory."""
    directory = out_root / figures.week
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "figures.json").write_text(figures.model_dump_json(indent=2) + "\n")
    review = None if run.review is None else run.review.model_dump(mode="json")
    (directory / "review.json").write_text(json.dumps(review, indent=2) + "\n")
    (directory / "run.json").write_text(run.model_dump_json(indent=2, exclude={"review"}) + "\n")
    (directory / "cost.json").write_text(run.cost.model_dump_json(indent=2) + "\n")
    (directory / "review.md").write_text(render_markdown(figures, run))
    return directory
