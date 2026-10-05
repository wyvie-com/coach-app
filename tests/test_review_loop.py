"""The hand-written loop against a scripted fake client. No network, no key, no retries."""

from __future__ import annotations

import json
from typing import Any

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from coach.evals.cases import CASES, build_case
from coach.figures import exercise_history, week_figures
from coach.review.loop import TURN_CAP, run_review
from coach.review.prompt import SYSTEM_PROMPT, render_user_turn
from coach.review.schema import REVIEW_JSON_SCHEMA

MODEL = "claude-haiku-4-5-20251001"
BENCH = "Bench Press (Barbell)"


def _usage(**kw: int) -> Usage:
    base = {"input_tokens": 1000, "output_tokens": 200}
    base.update(kw)
    return Usage(**base)


def _message(content: list, stop_reason: str, usage: Usage | None = None, **kw: Any) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model=MODEL,
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=usage or _usage(),
        **kw,
    )


def _tool_use(exercise: str, weeks: int, tool_id: str = "toolu_1") -> Message:
    block = ToolUseBlock(
        type="tool_use",
        id=tool_id,
        name="exercise_history",
        input={"exercise": exercise, "weeks": weeks},
    )
    return _message([block], "tool_use")


def _good_review() -> dict:
    return {
        "headline": "Bench stalled at 85 kg for five weeks while squat kept moving.",
        "highlights": [{"exercise": "Squat (Barbell)", "text": "Top set up again."}],
        "concerns": [{"exercise": BENCH, "text": "85 kg x 5 every week for five weeks."}],
        "suggestions": [
            {"exercise": BENCH, "text": "Drop to 80 kg and build back in 2.5 kg steps."}
        ],
    }


def _final(payload: str) -> Message:
    return _message([TextBlock(type="text", text=payload)], "end_turn")


class FakeMessages:
    def __init__(self, responses: list[Message]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("the fake client ran out of scripted responses")
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[Message]) -> None:
        self.messages = FakeMessages(responses)


@pytest.fixture(scope="module")
def stall():
    case = next(c for c in CASES if c.name == "bench_stall-1")
    data = build_case(case)
    return data.workouts, data.review_week, week_figures(data.workouts, data.review_week)


def test_tool_call_then_answer(stall) -> None:
    workouts, week, figures = stall
    client = FakeClient([_tool_use(BENCH, 5), _final(json.dumps(_good_review()))])

    run = run_review(client, MODEL, figures, workouts)

    assert run.outcome == "ok"
    assert run.review is not None and run.review.concerns[0].exercise == BENCH
    assert run.turns == 2
    assert [c.exercise for c in run.tool_calls] == [BENCH]
    assert run.tool_calls[0].is_error is False
    assert run.tool_calls[0].weeks == 5

    first, second = client.messages.calls
    # Request shape: stable system with one cache breakpoint, strict tool, one call per turn,
    # structured output, and a model we price.
    assert first["model"] == MODEL
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["system"][0]["text"] == SYSTEM_PROMPT
    assert first["tools"][0]["strict"] is True
    assert first["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert first["output_config"] == {
        "format": {"type": "json_schema", "schema": REVIEW_JSON_SCHEMA}
    }
    assert first["max_tokens"] == 4096
    assert "thinking" not in first
    blocks = first["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["text", "text"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in blocks[1]
    assert blocks[0]["text"] + "\n\n" + blocks[1]["text"] == render_user_turn(figures)
    # Second request carries the assistant turn verbatim and the tool result first in the user turn.
    assert second["messages"][1]["role"] == "assistant"
    assert second["messages"][1]["content"][0].type == "tool_use"
    result_block = second["messages"][2]["content"][0]
    assert result_block["type"] == "tool_result" and result_block["tool_use_id"] == "toolu_1"
    assert "is_error" not in result_block
    expected = exercise_history(workouts, BENCH, weeks=5, ending=week).model_dump(mode="json")
    assert json.loads(result_block["content"]) == expected
    # Cost is summed over both requests from the usage returned.
    assert len(run.requests) == 2
    assert run.cost.total_usd == pytest.approx(2 * (1000 * 1e-6 + 200 * 5e-6))


def test_refusal_is_recorded_and_no_content_is_read(stall) -> None:
    workouts, _, figures = stall
    refusal = _message(
        [],
        "refusal",
        stop_details={"type": "refusal", "category": "general_harms", "explanation": None},
    )
    run = run_review(FakeClient([refusal]), MODEL, figures, workouts)
    assert run.outcome == "refusal"
    assert run.review is None
    assert run.stop_details is not None and run.stop_details["category"] == "general_harms"
    assert run.turns == 1


def test_max_tokens_is_recorded_not_retried(stall) -> None:
    workouts, _, figures = stall
    client = FakeClient(
        [_message([TextBlock(type="text", text='{"headline": "cut off')], "max_tokens")]
    )
    run = run_review(client, MODEL, figures, workouts)
    assert run.outcome == "max_tokens"
    assert run.raw_text == '{"headline": "cut off'
    assert len(client.messages.calls) == 1


def test_invalid_json_is_recorded_not_retried(stall) -> None:
    workouts, _, figures = stall
    client = FakeClient([_final("not json at all")])
    run = run_review(client, MODEL, figures, workouts)
    assert run.outcome == "invalid_json"
    assert run.raw_text == "not json at all"
    assert run.error and "json" in run.error.lower()
    assert len(client.messages.calls) == 1


def test_schema_invalid_four_suggestions(stall) -> None:
    workouts, _, figures = stall
    bad = _good_review()
    bad["suggestions"] = bad["suggestions"] * 4
    run = run_review(FakeClient([_final(json.dumps(bad))]), MODEL, figures, workouts)
    assert run.outcome == "schema_invalid"
    assert run.review is None
    assert "suggestions" in (run.error or "")


def test_tool_error_round_trip(stall) -> None:
    workouts, _, figures = stall
    client = FakeClient([_tool_use("Bench", 4), _final(json.dumps(_good_review()))])
    run = run_review(client, MODEL, figures, workouts)
    assert run.outcome == "ok"
    assert run.tool_calls[0].is_error is True
    result_block = client.messages.calls[1]["messages"][2]["content"][0]
    assert result_block["is_error"] is True
    assert "Unknown exercise 'Bench'" in result_block["content"]
    assert BENCH in result_block["content"]


def test_tool_input_outside_schema_is_an_error_result(stall) -> None:
    workouts, _, figures = stall
    bad = ToolUseBlock(
        type="tool_use",
        id="toolu_9",
        name="exercise_history",
        input={"exercise": BENCH, "weeks": 40},
    )
    client = FakeClient([_message([bad], "tool_use"), _final(json.dumps(_good_review()))])
    run = run_review(client, MODEL, figures, workouts)
    assert run.tool_calls[0].is_error is True
    assert "weeks" in client.messages.calls[1]["messages"][2]["content"][0]["content"]


def test_unknown_tool_name_is_an_error_result(stall) -> None:
    workouts, _, figures = stall
    bad = ToolUseBlock(type="tool_use", id="toolu_9", name="delete_everything", input={})
    client = FakeClient([_message([bad], "tool_use"), _final(json.dumps(_good_review()))])
    run = run_review(client, MODEL, figures, workouts)
    assert run.tool_calls[0].is_error is True
    assert "delete_everything" in client.messages.calls[1]["messages"][2]["content"][0]["content"]


def test_turn_cap_stops_an_endless_tool_loop(stall) -> None:
    workouts, _, figures = stall
    client = FakeClient([_tool_use(BENCH, 4, tool_id=f"toolu_{i}") for i in range(TURN_CAP + 3)])
    run = run_review(client, MODEL, figures, workouts)
    assert run.outcome == "turn_cap"
    assert run.turns == TURN_CAP == 8
    assert len(client.messages.calls) == TURN_CAP


def test_pause_turn_is_continued_without_a_tool_result(stall) -> None:
    workouts, _, figures = stall
    paused = _message([TextBlock(type="text", text="thinking aloud")], "pause_turn")
    client = FakeClient([paused, _final(json.dumps(_good_review()))])
    run = run_review(client, MODEL, figures, workouts)
    assert run.outcome == "ok"
    assert client.messages.calls[1]["messages"][1]["role"] == "assistant"
    assert len(client.messages.calls[1]["messages"]) == 2


def test_cache_usage_flows_into_cost(stall) -> None:
    workouts, _, figures = stall
    usage = _usage(input_tokens=50, cache_creation_input_tokens=3000, cache_read_input_tokens=0)
    client = FakeClient(
        [_message([TextBlock(type="text", text=json.dumps(_good_review()))], "end_turn", usage)]
    )
    run = run_review(client, MODEL, figures, workouts)
    assert run.requests[0].cache_creation_input_tokens == 3000
    assert run.cost.cache_write_usd == pytest.approx(3000 * 1.25e-6)


def test_user_turn_carries_figures_and_week_but_never_notes() -> None:
    case = next(c for c in CASES if c.name == "negative_deload-1")
    data = build_case(case)
    figures = week_figures(data.workouts, data.review_week)
    text = render_user_turn(figures)
    assert "2026-W40" in text and "Deload" in text
    assert "notes" not in text and "description" not in text
    assert json.loads(text[text.index("{") : text.rindex("}") + 1])["week"] == "2026-W40"


def test_system_prompt_states_the_rules() -> None:
    for phrase in ("exercise_history", "three suggestions", "Overall", "RPE", "ten reps", "kg"):
        assert phrase in SYSTEM_PROMPT, phrase


def test_system_prompt_defines_stalled() -> None:
    assert "stalled" in SYSTEM_PROMPT.lower()
    assert "four or more" in SYSTEM_PROMPT
    assert "top_set_unchanged_weeks" in SYSTEM_PROMPT and "not a concern" in SYSTEM_PROMPT
