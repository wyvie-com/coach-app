"""The hand-written tool loop.

Every step is visible on purpose: send, read the stop reason before any content,
run the tool, return the result (with ``is_error`` when it failed), stop at the cap.
Nothing here retries on content: a refusal, a truncated answer, invalid JSON or a
schema failure is recorded and returned, so it can become an eval case.

Stop reasons and their handling follow the Claude docs (handling stop reasons page,
read 2026-10-05): ``tool_use`` run the tool; ``pause_turn`` send the content back;
``refusal`` read ``stop_details`` and stop; ``max_tokens`` the output is incomplete;
``end_turn`` read the answer. The SDK's own transport retries (connection errors,
408, 409, 429, 5xx) are left on; they are not content retries.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from typing import Any, Literal

from anthropic.types import Message, TextBlock, ToolUseBlock
from pydantic import BaseModel, ConfigDict, ValidationError

from coach.figures import UnknownExerciseError, WeekFigures, exercise_history
from coach.model import WeekId, Workout
from coach.pricing import Cost
from coach.pricing import cost as price
from coach.review.client import ClaudeClient
from coach.review.prompt import SYSTEM_PROMPT, user_turn_blocks
from coach.review.schema import EXERCISE_HISTORY_TOOL, REVIEW_JSON_SCHEMA, Review, ToolInput

TURN_CAP = 8
MAX_TOKENS = 4096

Outcome = Literal[
    "ok",
    "refusal",
    "max_tokens",
    "context_exceeded",
    "no_text",
    "invalid_json",
    "schema_invalid",
    "turn_cap",
    "api_error",
]


class ToolCall(BaseModel):
    """One tool call as the loop saw it. Results are not stored; they are recomputable."""

    model_config = ConfigDict(frozen=True)

    exercise: str
    weeks: int | None
    is_error: bool
    result_chars: int


class RequestUsage(BaseModel):
    """One request's usage and cost."""

    model_config = ConfigDict(frozen=True)

    model: str
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int
    total_usd: float


class ReviewRun(BaseModel):
    """Everything a review run produced, including the ways it failed."""

    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    model: str
    review: Review | None
    raw_text: str | None
    error: str | None = None
    stop_details: dict[str, Any] | None = None
    turns: int
    tool_calls: list[ToolCall]
    requests: list[RequestUsage]
    cost: Cost
    seconds: float


def build_request(
    model: str, figures: WeekFigures, *, max_tokens: int = MAX_TOKENS
) -> dict[str, Any]:
    """Every request's parameters. Cache breakpoints after the system prompt and the figures."""
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "tools": [EXERCISE_HISTORY_TOOL],
        "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
        "output_config": {"format": {"type": "json_schema", "schema": REVIEW_JSON_SCHEMA}},
        "messages": [{"role": "user", "content": user_turn_blocks(figures)}],
    }


def _text(message: Message) -> str:
    return "".join(block.text for block in message.content if isinstance(block, TextBlock))


def _run_tool(
    block: ToolUseBlock, workouts: Sequence[Workout], ending: WeekId
) -> tuple[str, bool, ToolCall]:
    """Execute one tool call. Errors become instructive text with ``is_error`` set."""
    exercise = str(block.input.get("exercise", "?")) if isinstance(block.input, dict) else "?"
    weeks = block.input.get("weeks") if isinstance(block.input, dict) else None
    weeks = weeks if isinstance(weeks, int) else None
    if block.name != EXERCISE_HISTORY_TOOL["name"]:
        text = f"Unknown tool {block.name!r}. The only tool is exercise_history."
        return (
            text,
            True,
            ToolCall(exercise=exercise, weeks=weeks, is_error=True, result_chars=len(text)),
        )
    try:
        params = ToolInput.model_validate(block.input)
    except ValidationError as exc:
        first = exc.errors()[0]
        text = f"Invalid input for exercise_history: {first['loc']}: {first['msg']}"
        return (
            text,
            True,
            ToolCall(exercise=exercise, weeks=weeks, is_error=True, result_chars=len(text)),
        )
    try:
        history = exercise_history(workouts, params.exercise, weeks=params.weeks, ending=ending)
    except UnknownExerciseError as exc:
        text = str(exc)
        return (
            text,
            True,
            ToolCall(exercise=exercise, weeks=weeks, is_error=True, result_chars=len(text)),
        )
    text = history.model_dump_json()
    return (
        text,
        False,
        ToolCall(
            exercise=history.exercise, weeks=params.weeks, is_error=False, result_chars=len(text)
        ),
    )


class ReviewSession:
    """One review as a resumable state machine: ask for the next request, hand back the response.

    The live loop and the batch runner both drive this, so the stop-reason rules exist once.
    ``next_request`` returns None once the run has finished; ``result`` then has the run.
    """

    def __init__(
        self,
        model: str,
        figures: WeekFigures,
        workouts: Sequence[Workout],
        *,
        turn_cap: int = TURN_CAP,
        max_tokens: int = MAX_TOKENS,
        batch: bool = False,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.model = model
        self.workouts = workouts
        self.turn_cap = turn_cap
        self.batch = batch
        self.clock = clock
        self.started = clock()
        self.request = build_request(model, figures, max_tokens=max_tokens)
        self.messages: list[dict[str, Any]] = self.request["messages"]
        self.ending = WeekId.parse(figures.week)
        self.tool_calls: list[ToolCall] = []
        self.requests: list[RequestUsage] = []
        self.costs: list[Cost] = []
        self.run: ReviewRun | None = None

    def next_request(self) -> dict[str, Any] | None:
        """The next Messages request, or None when the run is over."""
        if self.run is not None:
            return None
        if len(self.requests) >= self.turn_cap:
            self._finish("turn_cap", error=f"no final answer after {self.turn_cap} turns")
            return None
        # A fresh copy per request, so a recorded request is a snapshot and not a live list.
        return {**self.request, "messages": list(self.messages)}

    def result(self) -> ReviewRun:
        """The finished run. Only valid once ``next_request`` has returned None."""
        if self.run is None:
            raise RuntimeError("the review has not finished")
        return self.run

    def fail(self, error: str) -> None:
        """End the run because the request itself failed (an API or batch error)."""
        self._finish("api_error", error=error)

    def receive(self, response: Message) -> None:
        """Account for one response and either queue the next step or finish."""
        request_cost = price(response.usage, response.model, batch=self.batch)
        self.costs.append(request_cost)
        self.requests.append(
            RequestUsage(
                model=response.model,
                input_tokens=response.usage.input_tokens or 0,
                cache_creation_input_tokens=response.usage.cache_creation_input_tokens or 0,
                cache_read_input_tokens=response.usage.cache_read_input_tokens or 0,
                output_tokens=response.usage.output_tokens or 0,
                total_usd=request_cost.total_usd,
            )
        )

        # Stop reasons first. Content is read only when the stop reason says it is complete.
        if response.stop_reason == "refusal":
            details = response.stop_details.model_dump() if response.stop_details else None
            self._finish("refusal", stop_details=details)
            return
        if response.stop_reason == "max_tokens":
            self._finish("max_tokens", raw_text=_text(response))
            return
        if response.stop_reason == "model_context_window_exceeded":
            self._finish("context_exceeded", raw_text=_text(response))
            return

        self.messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "pause_turn":
            return
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if isinstance(block, ToolUseBlock):
                    text, is_error, record = _run_tool(block, self.workouts, self.ending)
                    self.tool_calls.append(record)
                    result: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": text,
                    }
                    if is_error:
                        result["is_error"] = True
                    results.append(result)
            self.messages.append({"role": "user", "content": results})
            return

        raw = _text(response)
        if not raw.strip():
            self._finish("no_text", raw_text=raw, error="the response had no text block")
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._finish("invalid_json", raw_text=raw, error=f"invalid JSON: {exc}")
            return
        try:
            review = Review.model_validate(payload)
        except ValidationError as exc:
            self._finish("schema_invalid", raw_text=raw, error=str(exc))
            return
        self._finish("ok", review=review, raw_text=raw)

    def _finish(self, outcome: Outcome, **extra: Any) -> None:
        self.run = ReviewRun(
            outcome=outcome,
            model=self.model,
            review=extra.pop("review", None),
            raw_text=extra.pop("raw_text", None),
            turns=len(self.requests),
            tool_calls=self.tool_calls,
            requests=self.requests,
            cost=Cost.total(self.costs, self.model),
            seconds=self.clock() - self.started,
            **extra,
        )


def run_review(
    client: ClaudeClient,
    model: str,
    figures: WeekFigures,
    workouts: Sequence[Workout],
    *,
    turn_cap: int = TURN_CAP,
    max_tokens: int = MAX_TOKENS,
    clock: Callable[[], float] = time.perf_counter,
) -> ReviewRun:
    """Run the loop for one week, live, and return everything it produced."""
    session = ReviewSession(
        model, figures, workouts, turn_cap=turn_cap, max_tokens=max_tokens, clock=clock
    )
    while (request := session.next_request()) is not None:
        session.receive(client.messages.create(**request))
    return session.result()
