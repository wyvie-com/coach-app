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

| Check | Catches | Does not catch |
| --- | --- | --- |
| `schema_valid` | Refusals, truncation, invalid JSON, a fourth suggestion, blank text, extra keys. | A review that is valid and wrong. |
| `story_found` | The planted story missing from the right section or filed under the wrong exercise. | A correct finding written so vaguely that a reader would miss it; the rubric's `specific` covers that. |
| `no_false_alarm` | Any concern about an exercise with no planted problem, including "Overall" when no sessions were planted missed. | A false alarm phrased as a highlight or a suggestion; a planted exercise flagged for the wrong reason. |
| `exercises_exist` | Invented or misspelt exercise names. | A real name attached to the wrong claim. |
| `kg_grounded` | Any kilogram figure in the headline, highlights or concerns that is not in the figures or a successful tool result, within 0.5 kg. | Percentages, rep counts, session counts and week numbers (not checked); a correct number attached to the wrong exercise; suggestions (deliberately excluded, they may propose new loads). |
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

## Live run

(filled in below once the run completes)
