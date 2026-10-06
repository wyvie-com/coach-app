# Slice 5: live runs and write-ups

Date: 2026-10-05. Branch `claude/funny-cori-evrx1v`. Commit `01a6351`, labelled v0.1.0.

## What was built

- `docs/live-runs.md`: the one-command sequence and what to read afterwards.
- Live runs for the last four complete weeks, 2026-W37 to W40, on Haiku: all four reviews reached `ok`, cost $0.010 to $0.026 and took 7 to 13 seconds. Every data-bound check passed at the time; the new `sessions_threshold` check, added from one of those weeks, fails that week on re-check.
- `coach review` now runs the five data-bound checks on every real week and writes `checks.json`; `coach rescore` re-runs the code checks over a stored `trials.jsonl`. Trial records store the review, the grader's reasons and the tool calls so re-scoring is free.
- Two findings from the real weeks became a case and a check (`docs/findings.md` entries 4 and 5); two from the eval became a check refinement and a prompt definition (entries 1 and 2); one grader fix (entry 3). A prompt sentence that measurably hurt stall detection was withdrawn the same day and replaced by a code-computed `top_set_unchanged_weeks` in the tool result.
- The harness records an API error (billing, auth, outage) as a trial with outcome `api_error`, stops, and still writes the report with a "stopped early" line. Found the hard way when the account's credit ran out mid-run.
- `README.md` for two audiences, `docs/architecture.md` with the trade-offs and the secrets and data boundary, `docs/findings.md`.
- Tests: 142 in total.

## Spend

| Run | Trials | Cost |
| --- | --- | --- |
| slice 3 live reviews | 2 | $0.04 |
| slice 4 smoke | 2 | $0.07 |
| first full run, Haiku and Sonnet | 90 | $3.65 |
| four real weeks | 4 | $0.07 |
| hold case, definition only | 3 | $0.11 |
| second full run, Haiku (stopped at 20 of 45) | 20 | $0.85 |
| hold and stall re-run (stopped at 5 of 9) | 5 | $0.21 |
| *credit exhausted; $5 top-up* | | |
| third full run, Haiku, 16 cases (unchanged-weeks count) | 48 | $1.84 |
| Opus 5.5 review of real week 2026-W40 | 1 | $0.11 |
| missed-sessions re-run after the rule-9 wording | 6 | $0.17 |
| Sonnet-graded run, 16 cases, 2 trials | 32 | $1.07 |
| Sonnet-graded run with tool results shown to the grader, 1 trial | 16 | $0.74 |
| **total** | | **$8.93** |

The slice estimate was $2; the second full run and the two hold runs were the overrun, taken to turn two real failures into measured ones. The account's prepaid credit ran out during the last two. After the top-up, the remaining measurements were run under the new `--budget-usd` cap.

## Decisions and rejected alternatives

- **Withdraw a prompt change that measured badly, even on a small sample.** Five trials is thin, but 3 of 5 against 6 of 6 on the same cases is the direction the sentence would be expected to push, and the fix that replaces it (code counts, model reads) is the project's thesis anyway.
- **Count unchanged weeks in code, not in the prompt.** Every other judgement the model makes is over a number the code computed; "how many weeks has this been flat" should be too.
- **Keep the `negative_two_week_hold` case although it currently fails.** A failing negative is a known gap with a number attached, which is more useful than a suite that only contains what passes.
- **Stop the harness on the first API error rather than skipping the trial.** A billing or auth error fails every later trial identically; stopping and writing the partial report is cheaper and clearer.
- **Record the credit exhaustion in the findings log** rather than hiding it in a note: it changed which numbers are partial.

## How to run it

See `docs/live-runs.md`. For this slice specifically:

```
uv run coach review --week 2026-W37      # and W38, W39, W40
uv run coach eval --trials 3
uv run coach rescore out/eval/<timestamp>/trials.jsonl --strict-grounding
```

## What it does not do yet

A full run with the rule-9 wording (the third run predates it). The two-week hold still fails 1 trial in 3. The two review weaknesses the Sonnet grader now names (findings entry 8). Slice 6 (Message Batches) is unstarted.

## Three questions an interviewer might ask

1. You changed the prompt, saw five trials, and reverted. Isn't that overfitting to noise? It would be, if the revert had been to the previous wording. It was to a different mechanism: the number the sentence asked the model to estimate is now computed by code and handed over. The five trials did not prove the sentence wrong; they showed its direction, and the replacement does not depend on them being right.
2. The credit ran out mid-run. What did the design get right and wrong? Right: every finished trial was on disk, so $0.85 of results survived a crash. Wrong: the harness let the exception propagate and wrote no report. It now records the error as a trial and writes a report marked "stopped early". The credential check at the start cannot catch a balance that runs out during the run; a spend estimate before starting, with confirmation above a threshold, is the next guard.
3. Why keep a check (`sessions_threshold`) for a rule the prompt already states? Because the prompt is a request and the check is a measurement. The real week showed the request being ignored once in four; without the check that would have stayed an impression.
