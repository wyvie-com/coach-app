"""The batch runner and the batched harness against a fake batches client. No network.

The fake answers each request's params the way the live harness fakes do, returns the
results in reverse order (the API promises no order), and can be told to error one
custom_id so the failure paths are exercised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anthropic.types import (
    ErrorResponse,
    InvalidRequestError,
    Message,
    TextBlock,
    ToolUseBlock,
    Usage,
)
from anthropic.types.messages import (
    MessageBatch,
    MessageBatchErroredResult,
    MessageBatchIndividualResponse,
    MessageBatchRequestCounts,
    MessageBatchSucceededResult,
)

from coach.evals.batch import BatchFailure, BatchRunner, custom_id
from coach.evals.cases import CASES
from coach.evals.harness import run_eval
from coach.evals.report import render_markdown

HAIKU = "claude-haiku-4-5-20251001"
BENCH, SQUAT = "Bench Press (Barbell)", "Squat (Barbell)"
REVIEW = {
    "headline": "Bench flat, squat moving.",
    "highlights": [{"exercise": SQUAT, "text": "Up again."}],
    "concerns": [{"exercise": BENCH, "text": "Same top set for five weeks."}],
    "suggestions": [],
}
SCORES = {
    d: {"score": 4, "reason": "r"} for d in ("follows_from_data", "specific", "safe", "concise")
}


def _message(content: list, stop: str) -> Message:
    return Message(
        id="msg",
        type="message",
        role="assistant",
        model=HAIKU,
        content=content,
        stop_reason=stop,
        stop_sequence=None,
        usage=Usage(input_tokens=1000, output_tokens=100),
    )


def _answer(params: dict[str, Any]) -> Message:
    """Reviewer: tool call first, then the fixed review. Grader: fixed scores."""
    if "tools" not in params:
        return _message([TextBlock(type="text", text=json.dumps(SCORES))], "end_turn")
    if len(params["messages"]) == 1:
        block = ToolUseBlock(
            type="tool_use", id="t1", name="exercise_history", input={"exercise": BENCH, "weeks": 5}
        )
        return _message([block], "tool_use")
    return _message([TextBlock(type="text", text=json.dumps(REVIEW))], "end_turn")


def _batch(batch_id: str, status: str, n: int) -> MessageBatch:
    return MessageBatch(
        id=batch_id,
        type="message_batch",
        processing_status=status,  # type: ignore[arg-type]
        request_counts=MessageBatchRequestCounts(
            processing=n if status != "ended" else 0,
            succeeded=n if status == "ended" else 0,
            errored=0,
            canceled=0,
            expired=0,
        ),
        created_at="2026-10-06T00:00:00Z",
        expires_at="2026-10-07T00:00:00Z",
        archived_at=None,
        cancel_initiated_at=None,
        ended_at=None,
        results_url=None,
    )


class FakeBatches:
    """create, retrieve, results; ``fail`` names custom_ids that come back errored."""

    def __init__(self, fail: dict[str, str] | None = None, polls_until_ended: int = 2) -> None:
        self.fail = fail or {}
        self.polls_until_ended = polls_until_ended
        self.created: list[list[dict[str, Any]]] = []
        self.polls: dict[str, int] = {}

    def create(self, *, requests: Any) -> MessageBatch:
        requests = list(requests)
        self.created.append(requests)
        batch_id = f"msgbatch_{len(self.created)}"
        self.polls[batch_id] = 0
        return _batch(batch_id, "in_progress", len(requests))

    def retrieve(self, message_batch_id: str) -> MessageBatch:
        self.polls[message_batch_id] += 1
        n = len(self.created[int(message_batch_id.split("_")[1]) - 1])
        ended = self.polls[message_batch_id] >= self.polls_until_ended
        return _batch(message_batch_id, "ended" if ended else "in_progress", n)

    def results(self, message_batch_id: str):
        requests = self.created[int(message_batch_id.split("_")[1]) - 1]
        for item in reversed(requests):  # any order, by design
            cid = item["custom_id"]
            if cid in self.fail:
                error = ErrorResponse(
                    type="error",
                    error=InvalidRequestError(type="invalid_request_error", message=self.fail[cid]),
                )
                yield MessageBatchIndividualResponse(
                    custom_id=cid, result=MessageBatchErroredResult(type="errored", error=error)
                )
            else:
                yield MessageBatchIndividualResponse(
                    custom_id=cid,
                    result=MessageBatchSucceededResult(
                        type="succeeded", message=_answer(item["params"])
                    ),
                )


def test_runner_keys_results_by_custom_id_and_polls_until_ended() -> None:
    fake = FakeBatches(fail={"b": "bad schema"}, polls_until_ended=3)
    slept: list[float] = []
    logged: list[str] = []
    runner = BatchRunner(fake, poll_seconds=7.0, sleep=slept.append, log=logged.append)
    grader_params = {"model": HAIKU, "messages": [{"role": "user", "content": "x"}]}
    out = runner.run({"a": grader_params, "b": grader_params, "c": grader_params})
    assert set(out) == {"a", "b", "c"}
    assert isinstance(out["a"], Message) and isinstance(out["c"], Message)
    failure = out["b"]
    assert isinstance(failure, BatchFailure)
    assert failure.kind == "errored" and failure.error_type == "invalid_request_error"
    assert "bad schema" in failure.describe()
    assert slept == [7.0, 7.0, 7.0] and runner.batch_ids == ["msgbatch_1"]
    assert any("ended" in line for line in logged)
    assert runner.run({}) == {} and fake.created and len(fake.created) == 1


def test_custom_ids_fit_the_documented_pattern() -> None:
    import re

    for case in CASES:
        for trial in (1, 3):
            assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", custom_id(case.name, trial))


def test_batched_harness_end_to_end(tmp_path: Path) -> None:
    fake = FakeBatches(polls_until_ended=1)
    runner = BatchRunner(fake, poll_seconds=0.0, sleep=lambda _: None)
    cases = [c for c in CASES if c.name in ("bench_stall-1", "negative_quiet-1")]
    report = run_eval(
        cases=cases,
        models=[HAIKU],
        trials=2,
        review_client=lambda _m: None,  # type: ignore[arg-type,return-value]
        grader_client=None,  # type: ignore[arg-type]
        grader_model=HAIKU,
        out_dir=tmp_path,
        batch=runner,
    )
    assert report.mode == "batch" and report.batch_ids == ["msgbatch_1", "msgbatch_2", "msgbatch_3"]
    # Round 1: four first requests. Round 2: four tool-result follow-ups. Then four grades.
    assert [len(r) for r in fake.created] == [4, 4, 4]
    assert "thinking" in fake.created[2][0]["params"]  # Haiku grader asks for thinking
    haiku = report.models[0]
    assert len(haiku.trials) == 4 and haiku.summary.outcomes == {"ok": 4}
    assert haiku.summary.tool_calls_mean == 1.0
    assert haiku.summary.checks["no_false_alarm"].passed == 2  # the quiet week is alarmed
    # Half price: two requests of 1000 in and 100 out at Haiku's $1 / $5 per MTok, halved.
    assert abs(haiku.trials[0].review_cost_usd - 2 * (1000 * 1 + 100 * 5) * 1e-6 * 0.5) < 1e-9
    assert haiku.trials[0].grader_thinking == "enabled" and haiku.trials[0].scores["safe"] == 4
    lines = (tmp_path / "trials.jsonl").read_text().splitlines()
    assert len(lines) == 4 and json.loads(lines[0])["review"]["headline"] == REVIEW["headline"]
    assert "- mode: batch (batch ids: msgbatch_1" in render_markdown(report)


def test_batched_harness_records_failed_requests_and_regrades_without_thinking(
    tmp_path: Path,
) -> None:
    quiet = custom_id("negative_quiet-1", 1)
    fake = FakeBatches(fail={quiet: "thinking is not supported"}, polls_until_ended=1)
    runner = BatchRunner(fake, poll_seconds=0.0, sleep=lambda _: None)
    cases = [c for c in CASES if c.name in ("bench_stall-1", "negative_quiet-1")]
    report = run_eval(
        cases=cases,
        models=[HAIKU],
        trials=1,
        review_client=lambda _m: None,  # type: ignore[arg-type,return-value]
        grader_client=None,  # type: ignore[arg-type]
        grader_model=HAIKU,
        out_dir=tmp_path,
        batch=runner,
    )
    by_case = {t.case: t for t in report.models[0].trials}
    # The quiet case's first review request errored, so it has no review and no grade.
    assert by_case["negative_quiet-1"].outcome == "api_error"
    assert "invalid_request_error" in by_case["negative_quiet-1"].check_details["schema_valid"]
    assert by_case["negative_quiet-1"].scores is None
    # The stall case was reviewed and graded; its grader request was never the failing id.
    assert by_case["bench_stall-1"].outcome == "ok" and by_case["bench_stall-1"].scores is not None
    assert [len(r) for r in fake.created] == [2, 1, 1]  # round 1, round 2 (stall only), grading


def test_batched_grader_falls_back_to_no_thinking_on_a_400(tmp_path: Path) -> None:
    class GraderRejectsThinking(FakeBatches):
        def results(self, message_batch_id: str):
            requests = self.created[int(message_batch_id.split("_")[1]) - 1]
            if any("thinking" in r["params"] for r in requests):
                self.fail = {r["custom_id"]: "thinking not allowed" for r in requests}
            else:
                self.fail = {}
            yield from super().results(message_batch_id)

    fake = GraderRejectsThinking(polls_until_ended=1)
    runner = BatchRunner(fake, poll_seconds=0.0, sleep=lambda _: None)
    cases = [c for c in CASES if c.name == "bench_stall-1"]
    report = run_eval(
        cases=cases,
        models=[HAIKU],
        trials=1,
        review_client=lambda _m: None,  # type: ignore[arg-type,return-value]
        grader_client=None,  # type: ignore[arg-type]
        grader_model=HAIKU,
        out_dir=tmp_path,
        batch=runner,
    )
    trial = report.models[0].trials[0]
    assert trial.grader_thinking == "off_after_400" and trial.scores is not None
    assert [len(r) for r in fake.created] == [1, 1, 1, 1]  # two review rounds, grade, regrade
    assert "thinking" not in fake.created[3][0]["params"]
