# Slice 6: the eval suite through Message Batches

Date: 2026-10-06. Branch `claude/funny-cori-evrx1v`. Step 4 of the follow-up plan.

## What was built

- `src/coach/evals/batch.py`: a `BatchRunner` that submits one dict of requests as a batch, polls `processing_status` until `ended`, and returns results keyed by `custom_id`; and `run_trials_batched`, which drives every review as rounds of batches and then grades in one more.
- `ReviewSession` in `src/coach/review/loop.py`: the loop as a resumable state machine (`next_request`, `receive`, `result`). `run_review` is now four lines on top of it, so the live path and the batch path share one set of stop-reason rules.
- The grader split the same way: `grader_request` and `parse_grade`, with `grade` on top for the live path. The "thinking rejected with a 400" fallback exists in both paths: live it is a second request, batched it is a second small batch.
- `coach eval --batch [--poll-seconds N]`; `pricing.cost(..., batch=True)` at the documented 50%; the report records `mode` and the batch ids.
- Tests: a fake batches client built from the SDK's own batch types, returning results in reverse order; the runner, the end-to-end batched harness, a failed request, and the grader fallback. 160 tests in total.

## Facts used (batch processing page, read 2026-10-06)

Official: 100,000 requests or 256 MB per batch; most batches finish within an hour, all end within 24; results kept 29 days; statuses `in_progress`, `canceling`, `ended`; result types `succeeded`, `errored`, `canceled`, `expired`, only `succeeded` billed; `custom_id` matches `^[a-zA-Z0-9_-]{1,64}$`; results may arrive in any order; 50% of standard prices; all active models; prompt caching works but the page suggests the 1-hour cache for better hit rates because batches can take longer than five minutes.

My reasoning: a review is a tool loop, so one batch cannot hold a whole review. Rounds of batches do it in two or three submissions for the whole suite. The 5-minute cache breakpoints are kept rather than switched to 1-hour, because the 1-hour write costs 2x against 1.25x and the hit rate inside a batch is not promised; the run reports what it got.

## Decisions and rejected alternatives

- **A state machine, not threads.** A blocking "batching client" with one thread per trial would have left `run_review` untouched, but it hides the control flow this project exists to show. The session makes every step visible and testable without a scheduler.
- **Records are written when the batches end, not per trial.** A batch has no per-trial moment. The ids are logged as each batch is created, and the API keeps results for 29 days, so a session that dies while waiting loses no paid work; the report carries the ids.
- **The budget cap applies between models in batch mode.** A batch cannot be stopped part-way without cancelling it, and cancelling throws away work already done. The estimate printed before the run is the control.
- **Grader fallback kept.** Haiku's thinking request is still sent first in a batch; if the API rejects it, those grades go again without thinking in a second batch, recorded as `off_after_400`, as in the live path.

## Live verification

Four cases (steady progress, bench stall, missed sessions, quiet week), one trial, Haiku reviews and Haiku grading, `--budget-usd 0.40`.

| | live run of 2026-10-06 (same prompt) | batched |
| --- | --- | --- |
| outcomes | ok | ok 4 of 4 |
| code checks | | 9 of 9 passed on every trial |
| review cost per review | $0.0103 | $0.0063 |
| grader cost per review | $0.0138 | $0.0066 |
| total for four trials | about $0.10 | $0.0515 |
| wall time | about 1 minute | 16 minutes, five batches (four review rounds, one grading) |
| grader thinking | enabled | enabled; the batch accepted the thinking request, no fallback needed |

The review cost is not exactly half because tool calls per review differed (1.1 live, 1.5 here, on different cases). Each batch of four requests took two to five minutes to end; the API's "most within an hour" is the figure to plan around, not these.

The full suite followed (findings entry 11): 48 trials, six batches (48, 47, 11, 7 and 1 review requests, then 48 grades), 34 minutes, $0.64 against $1.84 for the last live full run. The five review rounds are the tool-loop depth of the suite: one review needed five requests, most needed two.

## Interviewer questions

1. Why rounds of batches rather than one batch per review? Because a review's second request depends on its first response. The round structure is the dependency graph of a tool loop: every review's step N goes in batch N. Wall time is the number of rounds times the batch latency, which for this suite is minutes.
2. What changed in the live path to make this possible, and could that break it? The loop body moved from a function into a class with three methods. The function's tests all still pass unchanged against it, and the live path is the class plus a four-line driver. The risk is behavioural drift between the paths; there is none because there is one body.
3. What would you do differently at a thousand users? Batch the weekly reviews themselves, not just the evals: a thousand reviews a week have no latency requirement and would run in two or three rounds overnight at half price, with the batch ids as the job log.
