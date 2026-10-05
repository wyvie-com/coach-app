"""The eval suite through the Message Batches API, at half price and no hurry.

A review is a short tool loop, so it cannot go into one batch request. Instead every
unfinished review contributes its next request to a round; the round is one batch; the
responses go back into their sessions; repeat until no session wants another request.
Two or three rounds cover a suite. Grading is one more batch, with a second small one
for any grader request the API rejected with thinking on (as the live grader does).

Facts from the batch processing page (read 2026-10-06): a batch holds up to 100,000
requests or 256 MB; most finish within an hour and all end within 24; results stay
for 29 days; ``processing_status`` runs ``in_progress`` to ``ended``; each result is
``succeeded``, ``errored``, ``canceled`` or ``expired`` and only succeeded ones are
billed; results are matched by ``custom_id`` (1 to 64 characters of letters, digits,
hyphen and underscore) and may arrive in any order; usage is charged at 50% of the
standard prices. Prompt caching works across a batch's requests but a hit is not
promised, so the 5-minute breakpoints are kept and the hit rate is reported, not
assumed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from anthropic.types import Message
from pydantic import BaseModel, ConfigDict

from coach.evals.cases import BuiltCase
from coach.evals.grader import (
    GradeResult,
    grader_request,
    grader_thinking,
    histories_for,
    parse_grade,
)
from coach.figures import WeekFigures, week_figures
from coach.review.loop import TURN_CAP, ReviewRun, ReviewSession


class BatchesLike(Protocol):
    """The three calls the runner makes on ``client.messages.batches``."""

    def create(self, *, requests: Iterable[Any]) -> Any:
        """Submit one batch."""
        ...

    def retrieve(self, message_batch_id: str) -> Any:
        """Read a batch's status and request counts."""
        ...

    def results(self, message_batch_id: str) -> Iterable[Any]:
        """Stream a finished batch's results."""
        ...


class BatchFailure(BaseModel):
    """A request that came back as anything but ``succeeded``, or not at all."""

    model_config = ConfigDict(frozen=True)

    custom_id: str
    kind: str
    error_type: str | None = None
    message: str | None = None

    def describe(self) -> str:
        """One line for a run record."""
        detail = ": ".join(part for part in (self.error_type, self.message) if part)
        return f"batch request {self.kind}" + (f" ({detail})" if detail else "")


@dataclass
class BatchRunner:
    """Submit a dict of requests as one batch, wait for it, return results keyed by custom_id."""

    batches: BatchesLike
    poll_seconds: float = 30.0
    sleep: Callable[[float], None] = time.sleep
    log: Callable[[str], None] = lambda _: None
    batch_ids: list[str] = field(default_factory=list)

    def run(self, requests: dict[str, dict[str, Any]]) -> dict[str, Message | BatchFailure]:
        """One batch, polled until ``ended``. Results are read by custom_id, never by position."""
        if not requests:
            return {}
        batch = self.batches.create(
            requests=[{"custom_id": cid, "params": params} for cid, params in requests.items()]
        )
        self.batch_ids.append(batch.id)
        self.log(f"batch {batch.id}: {len(requests)} requests, {batch.processing_status}")
        while batch.processing_status != "ended":
            self.sleep(self.poll_seconds)
            batch = self.batches.retrieve(batch.id)
            counts = batch.request_counts
            self.log(
                f"batch {batch.id}: {batch.processing_status}, processing {counts.processing}, "
                f"succeeded {counts.succeeded}, errored {counts.errored}, "
                f"expired {counts.expired}, canceled {counts.canceled}"
            )
        out: dict[str, Message | BatchFailure] = {}
        for item in self.batches.results(batch.id):
            result = item.result
            if result.type == "succeeded":
                out[item.custom_id] = result.message
                continue
            inner = getattr(getattr(result, "error", None), "error", None)
            out[item.custom_id] = BatchFailure(
                custom_id=item.custom_id,
                kind=result.type,
                error_type=getattr(inner, "type", None),
                message=getattr(inner, "message", None),
            )
        for cid in set(requests) - set(out):
            out[cid] = BatchFailure(custom_id=cid, kind="missing from results")
        return out


@dataclass(frozen=True)
class BatchedTrial:
    """One case and trial after the batched review and grading."""

    data: BuiltCase
    trial: int
    figures: WeekFigures
    run: ReviewRun
    graded: GradeResult | None


def custom_id(case_name: str, trial: int) -> str:
    """Case names use letters, digits, hyphen and underscore, which is all a custom_id allows."""
    return f"{case_name}-t{trial}"


def run_trials_batched(
    runner: BatchRunner,
    *,
    model: str,
    built: Sequence[BuiltCase],
    trials: int,
    grader_model: str,
    turn_cap: int = TURN_CAP,
    log: Callable[[str], None] = lambda _: None,
) -> list[BatchedTrial]:
    """Review every case ``trials`` times in rounds of batches, then grade in one or two more."""
    figures_by_case = {
        data.case.name: week_figures(data.workouts, data.review_week) for data in built
    }
    sessions: dict[str, tuple[BuiltCase, int, ReviewSession]] = {}
    for data in built:
        for trial in range(1, trials + 1):
            session = ReviewSession(
                model, figures_by_case[data.case.name], data.workouts, turn_cap=turn_cap, batch=True
            )
            sessions[custom_id(data.case.name, trial)] = (data, trial, session)

    round_number = 0
    while True:
        pending = {
            cid: request
            for cid, (_, _, session) in sessions.items()
            if (request := session.next_request()) is not None
        }
        if not pending:
            break
        round_number += 1
        log(f"{model}: review round {round_number}, {len(pending)} requests")
        for cid, result in runner.run(pending).items():
            session = sessions[cid][2]
            if isinstance(result, BatchFailure):
                session.fail(result.describe())
            else:
                session.receive(result)

    thinking = grader_thinking(grader_model)
    mode = "enabled" if thinking else "off"
    to_grade = {
        cid: (data, session.result())
        for cid, (data, _, session) in sessions.items()
        if session.result().review is not None
    }
    requests = {
        cid: grader_request(
            grader_model,
            figures_by_case[data.case.name],
            run.review,  # type: ignore[arg-type]
            histories_for(run.tool_calls, data.workouts, figures_by_case[data.case.name].week),
            thinking=thinking,
        )
        for cid, (data, run) in to_grade.items()
    }
    graded: dict[str, GradeResult | None] = {}
    retry: dict[str, dict[str, Any]] = {}
    if requests:
        log(f"{grader_model}: grading, {len(requests)} requests")
    for cid, result in runner.run(requests).items():
        if isinstance(result, Message):
            graded[cid] = parse_grade(result, grader_model, mode, batch=True)
        elif thinking and result.error_type == "invalid_request_error":
            retry[cid] = {k: v for k, v in requests[cid].items() if k != "thinking"}
        else:
            graded[cid] = None
            log(f"{cid}: grader {result.describe()}")
    if retry:
        log(f"{grader_model}: grading again without thinking, {len(retry)} requests")
        for cid, result in runner.run(retry).items():
            if isinstance(result, Message):
                graded[cid] = parse_grade(result, grader_model, "off_after_400", batch=True)
            else:
                graded[cid] = None
                log(f"{cid}: grader {result.describe()}")

    return [
        BatchedTrial(
            data=data,
            trial=trial,
            figures=figures_by_case[data.case.name],
            run=session.result(),
            graded=graded.get(cid),
        )
        for cid, (data, trial, session) in sessions.items()
    ]
