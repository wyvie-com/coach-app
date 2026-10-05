"""Re-scoring stored trials offline: no model call, strict or refined grounding."""

from __future__ import annotations

import json
from pathlib import Path

from coach.evals.rescore import rescore

BENCH = "Bench Press (Barbell)"


def _row(case: str, headline: str, with_review: bool = True) -> dict:
    review = {
        "headline": headline,
        "highlights": [],
        "concerns": [{"exercise": BENCH, "text": "Flat for five weeks."}],
        "suggestions": [],
    }
    return {
        "case": case,
        "trial": 1,
        "model": "claude-haiku-4-5-20251001",
        "outcome": "ok" if with_review else "refusal",
        "checks": {},
        "check_details": {},
        "grade_outcome": None,
        "scores": None,
        "grade_reasons": None,
        "grader_thinking": None,
        "review": review if with_review else None,
        "tool_call_log": [{"exercise": BENCH, "weeks": 12, "is_error": False, "result_chars": 1}],
        "tool_calls": 1,
        "tool_errors": 0,
        "turns": 2,
        "seconds": 1.0,
        "review_cost_usd": 0.01,
        "grader_cost_usd": 0.0,
    }


def test_rescore_reports_strict_and_refined_grounding(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    rows = [
        _row("bench_stall-1", "Bench rose 2.5 kg a fortnight then stalled."),
        _row("bench_stall-2", "Bench is at 123.4 kg."),
        _row("steady_progress-1", "no review", with_review=False),
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    refined = rescore(path)
    strict = rescore(path, allow_differences=False)
    model = "claude-haiku-4-5-20251001"
    assert refined.skipped == 1  # the refusal row has no review to re-score
    assert refined.by_model[model]["kg_grounded"] == (1, 2)
    assert strict.by_model[model]["kg_grounded"] == (0, 2)
    assert refined.by_model[model]["concern_preceded_by_tool"] == (2, 2)
    assert refined.by_model[model]["story_found"] == (2, 2)
    assert refined.by_model[model]["sessions_threshold"] == (2, 2)
    text = refined.render()
    assert "kg_grounded" in text and model in text
