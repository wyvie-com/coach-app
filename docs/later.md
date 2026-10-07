# Later ideas

Things named during the build that are larger than this side project needs now. Each is a sentence so it can be picked up or discarded in one reading.

- Parallel `exercise_history` calls in one turn (currently `disable_parallel_tool_use`), once the eval shows the serial loop is a bottleneck.
- A `--thinking-budget` option for the review model, with the eval report showing whether it changes pass rates on Haiku.
- Configurable time zone instead of the `Australia/Melbourne` constant.
- Incremental sync with `GET /v1/workouts/events?since=` instead of a full pull each time.
- Using the SDK's `client.messages.parse()` helper once the two-step validation has been shown explicitly.
- A gitleaks configuration file with project-specific allow rules, if the default rules ever produce a false positive.
- Weekly hard sets per muscle group as a volume measure, which needs `GET /v1/exercise_templates` for `primary_muscle_group` (the research brought to the slice 2 gate names it the second metric for a high-rep log).
- Offline re-grading: grade stored reviews from a `trials.jsonl` with a different grader model without regenerating the reviews, so grader comparisons are on identical reviews.

- **Fewer fields in the figures.** After `leaders` and `counts` (findings entry 10) each exercise carries two percentage changes and the grader's remaining criticisms are percentages moved between them. A trimmed figures block for the model, with the full one kept for the files, is the next experiment: remove `volume_prior_week_kg` and `e1rm_change_4w_kg` (keep the percentages) and measure `follows_from_data` at three trials per case.
- **The "across the board" flourish.** Read in full (findings entries 15 and 16), five of the latest run's 48 reviews said it of five lifts in six, with the counts in front of the model and a rule against it. Two measurements before any more prompt: the same suite with Sonnet 5.5 as the reviewer (about $1.20 batched) to see whether it is a Haiku habit, and the shorter figures block above.
- **A fresh run through the fixed checks** (approved on 2026-10-07, not yet run): the same 16 cases, three trials each, batched, about $0.65, reading every failure. It is the only measure of the fixes in findings entry 16 on reviews they were not tuned on.
- **The grading limits in `docs/checks.md`:** kilogram figures attributed to the wrong exercise, metric or week; percentage direction and window; numbers in suggestions; rankings checked against the figure the sentence names; history lookups for progress claimed outside concerns; and a failing exit status, or an explicit inspection mode, for `coach review` when a check fails.
- **Calibrate the rubric grader** against a small set of reviews labelled by a person, kept apart from the cases the prompt has been tuned on.
