"""Re-run the code checks over stored trials. No model call, so a changed check is free to measure.

Rows written before the trial record carried the review cannot be re-scored and are
counted as skipped.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from coach.evals.cases import CASES, build_case
from coach.evals.checks import CHECK_NAMES, run_checks
from coach.figures import week_figures
from coach.pricing import Cost
from coach.review.loop import ReviewRun, ToolCall
from coach.review.schema import Review


@dataclass
class Rescore:
    """Pass counts per model per check, plus how many rows could not be scored."""

    by_model: dict[str, dict[str, tuple[int, int]]] = field(default_factory=dict)
    skipped: int = 0
    allow_differences: bool = True

    def render(self) -> str:
        """A small table."""
        lines = [f"grounding: {'differences allowed' if self.allow_differences else 'strict'}"]
        if self.skipped:
            lines.append(f"skipped {self.skipped} rows without a stored review")
        for model, checks in self.by_model.items():
            lines.append(model)
            for name in CHECK_NAMES:
                passed, total = checks[name]
                rate = passed / total if total else 0.0
                lines.append(f"  {name:<26} {rate:>4.0%} ({passed}/{total})")
        return "\n".join(lines)


def rescore(path: Path, *, allow_differences: bool = True) -> Rescore:
    """Score every stored review in ``path`` with the current checks."""
    cases = {c.name: c for c in CASES}
    built: dict[str, object] = {}
    counts: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    result = Rescore(allow_differences=allow_differences)
    zero = Cost(
        model="rescore", input_usd=0, cache_write_usd=0, cache_read_usd=0, output_usd=0, total_usd=0
    )
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if not row.get("review"):
            result.skipped += 1
            continue
        case = cases[row["case"]]
        if case.name not in built:
            built[case.name] = build_case(case)
        data = built[case.name]
        figures = week_figures(data.workouts, data.review_week)
        run = ReviewRun(
            outcome="ok",
            model=row["model"],
            review=Review.model_validate(row["review"]),
            raw_text=None,
            turns=row.get("turns", 0),
            tool_calls=[ToolCall.model_validate(c) for c in row.get("tool_call_log", [])],
            requests=[],
            cost=zero,
            seconds=0.0,
        )
        for check in run_checks(
            case, figures, run, data.workouts, allow_differences=allow_differences
        ):
            bucket = counts[row["model"]][check.name]
            bucket[0] += int(check.passed)
            bucket[1] += 1
    result.by_model = {
        model: {name: (c[name][0], c[name][1]) for name in CHECK_NAMES}
        for model, c in counts.items()
    }
    return result
