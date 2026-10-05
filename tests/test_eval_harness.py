"""The whole harness offline: a fixed scripted client, fifteen cases, predictable pass pattern."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from coach.evals.cases import CASES
from coach.evals.harness import ensure_credentials, run_eval
from coach.evals.report import render_markdown

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5-5"
BENCH, SQUAT = "Bench Press (Barbell)", "Squat (Barbell)"


def _message(content: list, stop: str, model: str) -> Message:
    return Message(
        id="msg",
        type="message",
        role="assistant",
        model=model,
        content=content,
        stop_reason=stop,
        stop_sequence=None,
        usage=Usage(input_tokens=1000, output_tokens=100),
    )


FIXED_REVIEW = {
    "headline": "Bench flat, squat PR, one session.",
    "highlights": [{"exercise": SQUAT, "text": "Best in twelve weeks."}],
    "concerns": [
        {"exercise": BENCH, "text": "Same top set for five weeks."},
        {"exercise": "Overall", "text": "One session this week."},
    ],
    "suggestions": [{"exercise": BENCH, "text": "Reset."}],
}


class FixedReviewer:
    """Tool call for bench, then one fixed review: right for some cases, wrong for others."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.messages = self
        self.calls = 0

    def create(self, **kwargs: Any) -> Message:
        self.calls += 1
        if len(kwargs["messages"]) == 1:
            block = ToolUseBlock(
                type="tool_use",
                id="t1",
                name="exercise_history",
                input={"exercise": BENCH, "weeks": 5},
            )
            return _message([block], "tool_use", kwargs["model"])
        return _message(
            [TextBlock(type="text", text=json.dumps(FIXED_REVIEW))], "end_turn", kwargs["model"]
        )


class FixedGrader:
    def __init__(self) -> None:
        self.messages = self
        self.calls = 0

    def create(self, **kwargs: Any) -> Message:
        self.calls += 1
        scores = {
            d: {"score": s, "reason": "r"}
            for d, s in zip(
                ("follows_from_data", "specific", "safe", "concise"), (4, 3, 5, 4), strict=True
            )
        }
        return _message([TextBlock(type="text", text=json.dumps(scores))], "end_turn", HAIKU)


def test_harness_end_to_end_offline(tmp_path: Path) -> None:
    reviewer = FixedReviewer(HAIKU)
    grader = FixedGrader()
    report = run_eval(
        cases=CASES,
        models=[SONNET, HAIKU],  # deliberately out of order
        trials=2,
        review_client=lambda model: reviewer,
        grader_client=grader,
        grader_model=HAIKU,
        out_dir=tmp_path,
    )
    assert [m.model for m in report.models] == [HAIKU, SONNET]  # Haiku first
    haiku = report.models[0]
    assert len(haiku.trials) == 16 * 2
    checks = haiku.summary.checks
    # The fixed review names bench, squat and Overall in every case.
    assert checks["schema_valid"].pass_rate == 1.0
    assert checks["exercises_exist"].pass_rate == 1.0
    assert checks["concern_preceded_by_tool"].pass_rate == 1.0
    assert checks["max_three_suggestions"].pass_rate == 1.0
    # story_found passes for bench_stall x2, squat_pr x2, missed_sessions x2, steady_progress x2
    # (any highlight), combined, and the three negatives (nothing expected): 12 cases.
    assert checks["story_found"].passed == 12 * 2 and checks["story_found"].total == 32
    assert checks["story_found"].stable_cases == 12
    # no_false_alarm: only combined-1 plants bench and missed sessions; every other case alarms.
    assert checks["no_false_alarm"].passed == 1 * 2
    assert haiku.summary.rubric["safe"].mean == 5.0 and haiku.summary.rubric["specific"].std == 0.0
    assert haiku.summary.tool_calls_mean == 1.0
    assert haiku.summary.outcomes == {"ok": 32}
    # The fixed review's "One session this week" concern fails sessions_threshold except where
    # sessions were planted missed: missed_sessions x2 and combined.
    assert checks["sessions_threshold"].passed == 3 * 2
    assert haiku.summary.cost_total_usd > 0 and haiku.summary.grader_cost_usd > 0
    # Files: report.md, report.json, and one JSONL line per trial written as it happened.
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["report.json", "report.md", "trials.jsonl"]
    lines = (tmp_path / "trials.jsonl").read_text().splitlines()
    assert len(lines) == 64 and json.loads(lines[0])["case"] == "steady_progress-1"
    first = json.loads(lines[0])
    assert first["review"]["headline"] == FIXED_REVIEW["headline"]  # re-scorable offline
    assert first["grade_reasons"]["safe"] == "r" and first["tool_call_log"][0]["exercise"] == BENCH
    markdown = (tmp_path / "report.md").read_text()
    assert markdown.index("| check") < markdown.index("## Cases")  # summary table first
    assert markdown.index(HAIKU) < markdown.index(SONNET)


def test_render_markdown_puts_models_side_by_side(tmp_path: Path) -> None:
    report = run_eval(
        cases=CASES[:2],
        models=[HAIKU, SONNET],
        trials=1,
        review_client=lambda model: FixedReviewer(model),
        grader_client=FixedGrader(),
        grader_model=HAIKU,
        out_dir=tmp_path,
    )
    text = render_markdown(report)
    header = next(line for line in text.splitlines() if line.startswith("| check"))
    assert HAIKU in header and SONNET in header


def test_ensure_credentials_refuses_without_a_working_route() -> None:
    class Raw:
        def list(self, *, limit: int):
            response = httpx.Response(
                401, request=httpx.Request("GET", "https://api.anthropic.com/v1/models")
            )
            raise anthropic.AuthenticationError("bad", response=response, body=None)

    class Models:
        with_raw_response = Raw()

    class Client:
        models = Models()

    with pytest.raises(RuntimeError, match="401"):
        ensure_credentials(Client())


def test_an_api_error_is_recorded_and_the_run_stops_with_a_report(tmp_path: Path) -> None:
    """A billing or auth error mid-run must not lose the paid trials or leave no report."""

    class FailingReviewer:
        def __init__(self) -> None:
            self.messages = self
            self.calls = 0

        def create(self, **kwargs: Any) -> Message:
            self.calls += 1
            if self.calls <= 2:  # one full trial (tool call then answer), then the account runs dry
                return FixedReviewer(HAIKU).create(**kwargs)
            response = httpx.Response(
                400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            )
            raise anthropic.BadRequestError(
                "Your credit balance is too low", response=response, body=None
            )

    reviewer = FailingReviewer()
    report = run_eval(
        cases=CASES[:3],
        models=[HAIKU],
        trials=2,
        review_client=lambda model: reviewer,
        grader_client=FixedGrader(),
        grader_model=HAIKU,
        out_dir=tmp_path,
    )
    haiku = report.models[0]
    assert [t.outcome for t in haiku.trials] == ["ok", "api_error"]
    assert haiku.summary.outcomes == {"api_error": 1, "ok": 1}
    assert "credit balance" in haiku.trials[1].check_details["schema_valid"]
    assert (
        report.stopped_early
        == "claude-haiku-4-5-20251001 steady_progress-1 trial 2: BadRequestError"
    )
    assert (tmp_path / "report.md").exists() and (tmp_path / "report.json").exists()
    assert "stopped early" in (tmp_path / "report.md").read_text()


def test_budget_cap_stops_the_run_and_is_recorded(tmp_path: Path) -> None:
    class PricedReviewer(FixedReviewer):
        def create(self, **kwargs: Any) -> Message:
            msg = super().create(**kwargs)
            return msg.model_copy(update={"usage": Usage(input_tokens=100_000, output_tokens=1000)})

    report = run_eval(
        cases=CASES[:4],
        models=[HAIKU],
        trials=1,
        review_client=lambda model: PricedReviewer(model),
        grader_client=FixedGrader(),
        grader_model=HAIKU,
        out_dir=tmp_path,
        budget_usd=0.25,  # each trial costs about $0.21 at 100k input tokens per request
    )
    haiku = report.models[0]
    assert len(haiku.trials) == 2  # the second trial crossed the cap; nothing started after it
    assert report.stopped_early is not None and "budget" in report.stopped_early
    assert report.total_cost_usd > 0.25


def test_estimate_cost() -> None:
    from coach.evals.harness import estimate_usd

    assert estimate_usd(cases=16, trials=3, models=2) == pytest.approx(16 * 3 * 2 * 0.045)
