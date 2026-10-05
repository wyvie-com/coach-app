# Later ideas

Things named during the build that are larger than this side project needs now. Each is a sentence so it can be picked up or discarded in one reading.

- Parallel `exercise_history` calls in one turn (currently `disable_parallel_tool_use`), once the eval shows the serial loop is a bottleneck.
- A `--thinking-budget` option for the review model, with the eval report showing whether it changes pass rates on Haiku.
- Configurable time zone instead of the `Australia/Melbourne` constant.
- Incremental sync with `GET /v1/workouts/events?since=` instead of a full pull each time.
- Using the SDK's `client.messages.parse()` helper once the two-step validation has been shown explicitly.
- Message Batches for the eval harness (slice 6, optional).
- A gitleaks configuration file with project-specific allow rules, if the default rules ever produce a false positive.
- Weekly hard sets per muscle group as a volume measure, which needs `GET /v1/exercise_templates` for `primary_muscle_group` (the research brought to the slice 2 gate names it the second metric for a high-rep log).
- Volume by muscle group, which needs `GET /v1/exercise_templates` for the `primary_muscle_group` field.
- A `coach eval --rescore <trials.jsonl>` command that re-runs the code checks over stored reviews without paying for new ones; the trial record now carries the review for this reason.
