# Slice 4: evals

Date: 2026-10-05. Branch `claude/funny-cori-evrx1v`.

## What was built

- `coach.evals.checks`: seven code checks over one review run, in a fixed order, each returning pass or fail with a one-line reason. A run with no review fails all seven.
- `coach.evals.grader`: a separate model call that sees the figures and the review, never the case or the expected finding, and returns four scores of 1 to 5 with reasons through `output_config.format`, validated again with Pydantic. On Haiku 4.5 it asks for manual extended thinking (`budget_tokens` 1,024, `max_tokens` 4,096); if the API rejected that combination with a 400 the grader would send once more without thinking and record `off_after_400`. On Sonnet 5.5 and Opus 5.5 the parameter is omitted and adaptive thinking applies. Thinking tokens are costed like everything else.
- `coach.evals.harness`: runs every case for every trial for every model, checks first and rubric second, appends each trial to `trials.jsonl` as it finishes, then writes `report.json` and `report.md`. Haiku is always the first column. `ensure_credentials` refuses to start a paid run unless the Anthropic route answers 200.
- `coach.evals.report`: Markdown with the summary table first (per check pass rate and the count of cases that passed in every trial; per rubric dimension mean, spread, min, max; outcomes; tool calls, seconds and cost per review; totals), then one block per case with every trial's failed checks and scores.
- `coach eval --model A [--model B] --trials 3 --grader-model G [--cases a,b]`.
- Two fixes found by the first live smoke run: the grader's token ceiling was too close to its thinking budget and hit `max_tokens` once; and accessory lifts in the synthetic logs wobbled by 2.5 kg every week from the seed, which planted an accidental regression that the model duly reported. Accessories now take one fixed offset per case.
- Tests: 22 new, 132 in total. Every check against a review built to pass it and one built to fail it; the grader's request shape, the thinking fallback, refusal and bad JSON; the whole harness offline against a fixed scripted reviewer whose pass pattern across the fifteen cases is predicted in the test; report ordering; the credential refusal.

## What each check can and cannot catch

As written at slice 4 and extended in the follow-up. `story_found` and `flags_in_concerns` were replaced on 2026-10-07 (findings entry 13); current definitions are in `docs/checks.md`.

| Check | Catches | Does not catch |
| --- | --- | --- |
| `schema_valid` | Refusals, truncation, invalid JSON, a fourth suggestion, blank text, extra keys. | A review that is valid and wrong. |
| `story_found` | The planted story missing from the right section or filed under the wrong exercise. | A correct finding written so vaguely that a reader would miss it; the rubric's `specific` covers that. |
| `no_false_alarm` | Any concern about an exercise with no planted problem, including "Overall" when no sessions were planted missed. | A false alarm phrased as a highlight or a suggestion; a planted exercise flagged for the wrong reason. |
| `exercises_exist` | Invented or misspelt exercise names. | A real name attached to the wrong claim. |
| `kg_grounded` | Any kilogram figure in the headline, highlights or concerns that is not in the figures or a successful tool result, within 0.5 kg. | Percentages, rep counts, session counts and week numbers (not checked); a correct number attached to the wrong exercise; suggestions (deliberately excluded, they may propose new loads). |
| `comparisons_grounded` | A superlative (fastest, largest, strongest and the like) about an exercise that leads on no figure, an "Overall" superlative naming no leader, and "all" or "every" exercises progressing when `counts` says otherwise. Added in the follow-up, findings entry 10. | "highest" and "best", which usually compare an exercise with its own history; a wrong percentage attached to the right exercise; the window a change is labelled with. |
| `flags_in_concerns` | A flag the code raised (stall of four or more weeks, four-week e1RM fall outside a deload, sessions missed) that the review did not put in concerns under that exercise. Added in the follow-up, findings entry 12. | A concern that names the exercise for the wrong reason; a flag the thresholds do not raise. |
| `pct_grounded` | A percentage in a finding about one exercise that is not that exercise's own figure or tool result, within 0.05; the headline and "Overall" findings may quote any exercise's. Added in the follow-up, findings entry 12. | A percentage computed from two grounded ones; the window a percentage is labelled with. |
| `deload_grounded` | "Deload" said of the week in the headline, a highlight or a concern when no session title contains it. Added in the follow-up, findings entry 12. | A suggestion to deload, which is advice and deliberately excluded. |
| `concern_preceded_by_tool` | A trend judgement made without looking at the history. | A tool call for the right exercise but too short a window to see the story. |
| `max_three_suggestions` | Redundant with `schema_valid` while Pydantic enforces the cap; kept so the count is visible if the schema ever changes. | Three bad suggestions. |

Known blind spots: the checks read exact exercise names and kilogram numbers, so a review that is right in substance but paraphrases a name fails, and a review that quotes the right number about the wrong thing passes. The grounding check cannot tell a copied figure from a coincidentally correct one. The negatives are two cases; a model that never raises a concern would pass them and fail only the positive stories. None of the checks reads the suggestions beyond counting them; that is the rubric's job.

## How to add a case from a real failure in under ten minutes

1. Read `out/<week>/review.md` and `run.json` and name the failure in one sentence: which section, which exercise, what the review said, what the figures showed.
2. Add a `Story` value and its expectation to `_EXPECTED` in `src/coach/evals/cases.py`. The expectation is a section and an exercise name, or "Overall", or "any".
3. Plant it in `_load_and_rpe`: one `if` that edits one lift's load or RPE for the relevant weeks. Use the existing stories as templates; a stall holds a load, a regression scales it, a PR adds to the review week.
4. Add one test in `tests/test_planted_stories.py` that asserts the story is visible in `week_figures` or `exercise_history` by code alone. If it is not visible there, the eval cannot expect the model to find it.
5. Add the case name to the count in `test_case_list_matches_the_spec` and run `uv run pytest`.
6. Run `uv run coach eval --cases <new-case> --trials 3` and record the pass rate in `docs/findings.md`.

No real data is copied: the case is a planted pattern, not the week that failed.

## Live run (2026-10-05, 15 cases, 3 trials, grader Haiku 4.5 with thinking)

Smoke run first: two cases, one trial, $0.07. It found the two fixes above. Then the full run: 90 reviews and 90 grades, 53 minutes, $3.65 in total.

| | Haiku 4.5 | Sonnet 5.5 |
| --- | --- | --- |
| schema_valid | 100% (45/45) | 100% (45/45) |
| story_found | 87% (39/45), stable 12/15 cases | 100% (45/45), stable 15/15 |
| no_false_alarm | 100% | 100% |
| exercises_exist | 100% | 100% |
| kg_grounded | 67% (30/45), stable 6/15 | 91% (41/45), stable 11/15 |
| concern_preceded_by_tool | 100% | 100% |
| max_three_suggestions | 100% | 100% |
| follows_from_data (1 to 5) | 3.47 ± 1.17 (n 43) | 3.55 ± 0.74 (n 40) |
| specific | 4.49 ± 0.54 | 4.75 ± 0.43 |
| safe | 4.84 ± 0.37 | 4.95 ± 0.22 |
| concise | 4.23 ± 0.77 | 4.15 ± 0.53 |
| tool calls per review | 2.98 | 3.84 |
| seconds per review | 30.0 | 40.0 |
| review cost per review | $0.0181 | $0.0327 |
| total (reviews plus grading) | $1.44 | $2.21 |

Every review on both models reached `ok`: no refusal, no truncation, no invalid JSON, no schema failure, no tool error, no false alarm, no invented exercise, no concern without a tool call. The differences are in two checks and in cost.

**What Haiku missed.** All six `story_found` failures are the same story: the bench press held at one load for five weeks at a steady RPE, and Haiku did not put it in concerns (both `bench_stall` seeds and all three `combined` trials; in one `combined` trial it also missed the missed sessions). It had called the tool for bench and seen five identical top sets; it described them as steady rather than stalled. Sonnet filed the stall as a concern every time. This is the one place in the suite where the larger model is clearly better, and it is a judgement call about what "stalled" means that the prompt can make explicit.

**What `kg_grounded` is really catching.** Of the 15 Haiku failures and 4 Sonnet failures, almost every ungrounded number is 2.5, 5.0 or 7.5: the model stating a week-to-week load step it computed from two grounded figures ("up 2.5 kg a fortnight"). The one other value (8.8) was a correct e1RM difference. None was invented. The check is stricter than the spec's intent, which was to catch numbers that come from nowhere. The planned refinement, recorded for `docs/findings.md` in slice 5 with a before-and-after pass rate, is to accept the difference between two grounded figures for the same exercise. The trial record now stores the review so that re-scoring is an offline operation.

**Grader.** Haiku 4.5 accepted thinking together with structured output on all 90 calls; the 400 fallback never fired. Seven grades (2 Haiku-reviewed, 5 Sonnet-reviewed) ended in `max_tokens` because thinking overran the 1,024 target well past a 4,096 ceiling, so the grader's `max_tokens` is now 8,192 and those seven are missing from the rubric means above (n 43 and n 40). The grader's `follows_from_data` is the dimension with the widest spread and the one most often at 2; three of Haiku's `negative_quiet` reviews scored 2 there, which says the grader and the review disagree about what a quiet week deserves. The grader's reasons are now stored per trial so the next run can say why.

**Cost.** A Haiku review costs $0.018 and a Sonnet review $0.033, so Sonnet is 1.8 times the price for a 13-point gain on story detection and a 24-point gain on grounding, with the grounding gap mostly the arithmetic described above. Grading at Haiku costs about $0.015 per review on top. The brief's trade-off question now has numbers; the architecture note in slice 5 makes the call.

## Decisions and rejected alternatives

- **Trials appended to JSONL as they finish.** A rate limit or a crash at trial 80 of 90 keeps 80 paid results. Rejected: building the report in memory only.
- **Grader never sees the case.** The user turn contains the figures and the review and nothing else; the test asserts the case name, the word "expected" and the word "planted" are absent. Rejected: telling the grader what to look for, which would make it a second code check.
- **Same model as grader by default, with the model named in every report.** The brief fixes the default; the eval guide prefers a different model. The report carries `grader_model` so a Sonnet-graded run is a one-flag comparison.
- **Checks fail closed when there is no review.** A refused or truncated run counts as failing every check rather than being excluded, so a model that refuses often cannot look good.
- **Strict grounding kept for this run.** Refining the check before measuring would have hidden the finding. The refinement is the first entry for the findings log.
- **Haiku first in the report** by rule, whatever order `--model` was given in.

## How to run it

```
uv run pytest
uv run coach eval --cases bench_stall-1,negative_quiet-1 --trials 1        # smoke, about $0.07
uv run coach eval --trials 3                                              # Haiku, about $1.50
uv run coach eval --model claude-haiku-4-5-20251001 --model claude-sonnet-5-5 --trials 3
uv run coach eval --grader-model claude-sonnet-5-5 --trials 3
```

## What it does not do yet

No offline re-scoring command (the data for it is now stored). No RPE-free variant of the cases, although the real log has no RPE. No batch path. No Opus run yet. The prompt has not been changed in response to these numbers; that is deliberate, so slice 5 can show a before and after.

## Three questions an interviewer might ask

1. Haiku missed the bench stall six times and Sonnet never did. Is that a prompt problem or a model problem? Both are plausible and the suite can tell them apart: change the prompt to define "stalled" (same top set for four or more weeks at steady RPE), re-run both models, and see whether Haiku's story_found moves. If it does, it was the prompt. If Sonnet stays at 100 and Haiku stays at 87, the capability gap is real and the cost table says whether it is worth 1.8 times the price.
2. Two thirds of Haiku's grounding failures are "2.5 kg". Is the check wrong? The check implements the spec literally, and the spec was written to catch invented numbers. A difference between two numbers in the data is derived, not invented. The honest sequence is: run the strict check, measure, record the finding, refine the check with a stated rule, re-score the stored reviews, and report both pass rates. Loosening the check first would have hidden what the model actually does.
3. Why store the review in every trial record when the report only needs the scores? Because checks change. Re-scoring 90 stored reviews is free; regenerating them costs $2.30 and gives different reviews, so the before-and-after would not be comparable.
