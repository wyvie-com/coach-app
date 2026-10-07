"""The eval report as Markdown: one summary table first, models side by side, then the cases."""

from __future__ import annotations

from coach.evals.checks import CHECK_NAMES
from coach.evals.grader import RUBRIC
from coach.evals.harness import CheckSummary, EvalReport


def _check_cell(c: CheckSummary) -> str:
    if c.total == 0:
        return f"n/a ({c.not_applicable} trials)"
    cell = f"{c.pass_rate:.0%} ({c.passed}/{c.total})"
    if c.not_applicable:
        cell += f", n/a {c.not_applicable}"
    return cell + f", stable {c.stable_cases}/{c.cases}"


def render_markdown(report: EvalReport) -> str:
    """Render the report. The JSON beside it is the authoritative form."""
    models = [m.model for m in report.models]
    lines = [
        "# Eval report",
        "",
        f"- created: {report.created_at}",
        f"- cases: {len(report.cases)}, trials per case: {report.trials}",
        f"- grader: {report.grader_model}",
        f"- total cost: ${report.total_cost_usd:.4f}",
        f"- mode: {report.mode}"
        + (f" (batch ids: {', '.join(report.batch_ids)})" if report.batch_ids else ""),
    ]
    if report.stopped_early:
        lines.append(
            f"- **stopped early** at {report.stopped_early}; the tables cover the trials that ran"
        )
    lines += [
        "",
        "## Summary",
        "",
        "Each pass rate is over the trials a check could test. n/a counts the trials it could "
        "not: expected_placement on a negative case, the flag checks in a week with no flags. "
        "A pass means the check found nothing wrong within what it reads; docs/checks.md says "
        "what each check does not test.",
        "",
        "| check | " + " | ".join(models) + " |",
        "| --- | " + " | ".join("---" for _ in models) + " |",
    ]
    for name in CHECK_NAMES:
        cells = []
        for m in report.models:
            cells.append(_check_cell(m.summary.checks[name]))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append(
        "| negative cases: no unplanted concern | "
        + " | ".join(
            "-" if m.summary.negative_cases is None else _check_cell(m.summary.negative_cases)
            for m in report.models
        )
        + " |"
    )
    lines += [
        "",
        "| rubric (1 to 5) | " + " | ".join(models) + " |",
        "| --- | " + " | ".join("---" for _ in models) + " |",
    ]
    for dim in RUBRIC:
        cells = []
        for m in report.models:
            r = m.summary.rubric.get(dim)
            cells.append(
                "-"
                if r is None
                else f"{r.mean:.2f} ± {r.std:.2f} (min {r.min}, max {r.max}, n {r.n})"
            )
        lines.append(f"| {dim} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "| run | " + " | ".join(models) + " |",
        "| --- | " + " | ".join("---" for _ in models) + " |",
    ]
    rows = [
        ("outcomes", lambda s: ", ".join(f"{k} {v}" for k, v in s.outcomes.items())),
        ("tool calls per review", lambda s: f"{s.tool_calls_mean:.2f}"),
        ("seconds per review", lambda s: f"{s.seconds_mean:.1f}"),
        ("review cost per review", lambda s: f"${s.review_cost_mean_usd:.4f}"),
        ("review cost total", lambda s: f"${s.review_cost_usd:.4f}"),
        ("grader cost total", lambda s: f"${s.grader_cost_usd:.4f}"),
        ("cost total", lambda s: f"${s.cost_total_usd:.4f}"),
    ]
    for label, fn in rows:
        lines.append(f"| {label} | " + " | ".join(fn(m.summary) for m in report.models) + " |")
    lines += ["", "## Cases", ""]
    for case in report.cases:
        lines.append(f"### {case}")
        for m in report.models:
            for t in (t for t in m.trials if t.case == case):
                failed = [n for n, ok in t.checks.items() if ok is False]
                scores = "-" if not t.scores else "/".join(str(t.scores[d]) for d in RUBRIC)
                detail = "; ".join(f"{n}: {t.check_details[n]}" for n in failed)
                cost = t.review_cost_usd + t.grader_cost_usd
                lines.append(
                    f"- {m.model} trial {t.trial}: {t.outcome}, failed {len(failed)}"
                    + (f" [{detail}]" if detail else "")
                    + f", rubric {scores}, tool calls {t.tool_calls}, ${cost:.4f}"
                )
        lines.append("")
    return "\n".join(lines)
