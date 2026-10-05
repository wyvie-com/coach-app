"""The rubric grader: separate model, sees figures and review, never the expected finding."""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx
from anthropic.types import Message, TextBlock, Usage

from coach.evals.cases import CASES, build_case
from coach.evals.grader import GRADER_JSON_SCHEMA, RUBRIC, grade, grader_thinking
from coach.figures import week_figures
from coach.review.schema import Finding, Review

HAIKU = "claude-haiku-4-5-20251001"


def _message(text: str, stop: str = "end_turn", model: str = HAIKU, **usage: int) -> Message:
    base = {"input_tokens": 3000, "output_tokens": 150}
    base.update(usage)
    return Message(
        id="msg",
        type="message",
        role="assistant",
        model=model,
        content=[TextBlock(type="text", text=text)],
        stop_reason=stop,
        stop_sequence=None,
        usage=Usage(**base),
    )


class FakeMessages:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, responses: list) -> None:
        self.messages = FakeMessages(responses)


def _scores() -> dict:
    return {
        dim: {"score": s, "reason": f"{dim} reason"}
        for dim, s in zip(RUBRIC, (4, 3, 5, 4), strict=True)
    }


def _inputs():
    data = build_case(next(c for c in CASES if c.name == "bench_stall-1"))
    figures = week_figures(data.workouts, data.review_week)
    review = Review(
        headline="Bench stalled.",
        highlights=[],
        concerns=[Finding(exercise="Bench Press (Barbell)", text="Flat for five weeks.")],
        suggestions=[],
    )
    return data, figures, review


def test_rubric_dimensions_and_schema() -> None:
    assert RUBRIC == ("follows_from_data", "specific", "safe", "concise")
    for dim in RUBRIC:
        prop = GRADER_JSON_SCHEMA["properties"][dim]
        assert prop["properties"]["score"]["enum"] == [1, 2, 3, 4, 5]
        assert prop["additionalProperties"] is False
    assert GRADER_JSON_SCHEMA["additionalProperties"] is False


def test_grader_sees_figures_and_review_but_not_the_case() -> None:
    data, figures, review = _inputs()
    client = FakeClient([_message(json.dumps(_scores()))])
    result = grade(client, HAIKU, figures, review)
    assert result.outcome == "ok"
    assert result.scores == {"follows_from_data": 4, "specific": 3, "safe": 5, "concise": 4}
    assert result.reasons["safe"] == "safe reason"
    call = client.messages.calls[0]
    user_text = json.dumps(call["messages"])
    assert "Bench stalled." in user_text and figures.week in user_text
    for forbidden in ("bench_stall", "expected", "planted", "story"):
        assert forbidden not in user_text.lower(), forbidden
    assert call["output_config"]["format"]["schema"] == GRADER_JSON_SCHEMA
    assert call["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert call["max_tokens"] == 4096
    assert result.thinking == "enabled"
    assert result.cost.total_usd > 0


def test_grader_thinking_config_by_model() -> None:
    assert grader_thinking(HAIKU) == {"type": "enabled", "budget_tokens": 1024}
    assert grader_thinking("claude-haiku-4-5") == {"type": "enabled", "budget_tokens": 1024}
    assert grader_thinking("claude-sonnet-5-5") is None  # adaptive thinking is on by default


def test_grader_falls_back_to_no_thinking_on_a_400_and_records_it() -> None:
    data, figures, review = _inputs()
    response = httpx.Response(
        400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    rejected = anthropic.BadRequestError(
        "thinking not supported with output_config", response=response, body=None
    )
    client = FakeClient([rejected, _message(json.dumps(_scores()))])
    result = grade(client, HAIKU, figures, review)
    assert result.outcome == "ok"
    assert result.thinking == "off_after_400"
    assert "thinking" not in client.messages.calls[1]


def test_grader_records_refusal_and_bad_json_without_retrying() -> None:
    data, figures, review = _inputs()
    client = FakeClient([_message("", stop="refusal")])
    assert grade(client, HAIKU, figures, review).outcome == "refusal"
    client = FakeClient([_message("not json")])
    result = grade(client, HAIKU, figures, review)
    assert result.outcome == "invalid_json" and result.scores is None
    assert len(client.messages.calls) == 1


def test_grader_thinking_tokens_are_part_of_the_cost() -> None:
    data, figures, review = _inputs()
    msg = _message(json.dumps(_scores()), output_tokens=1200)
    result = grade(FakeClient([msg]), HAIKU, figures, review)
    assert result.cost.output_usd > 0.005
