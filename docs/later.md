# Later ideas

Things named during the build that are larger than this side project needs now. Each is a sentence so it can be picked up or discarded in one reading.

- Parallel `exercise_history` calls in one turn (currently `disable_parallel_tool_use`), once the eval shows the serial loop is a bottleneck.
- A `--thinking-budget` option for the review model, with the eval report showing whether it changes pass rates on Haiku.
- Configurable time zone instead of the `Australia/Melbourne` constant.
- Incremental sync with `GET /v1/workouts/events?since=` instead of a full pull each time.
- Using the SDK's `client.messages.parse()` helper once the two-step validation has been shown explicitly.
- Message Batches for the eval harness (slice 6, optional).
- A gitleaks configuration file with project-specific allow rules, if the default rules ever produce a false positive.
- An e1RM formula that holds above ten reps, or a rule that reports no e1RM for sets above a rep ceiling. Epley overstates badly at 16 to 20 reps, which is most of my real training (seen in the slice 2 dry run).
- Volume by muscle group, which needs `GET /v1/exercise_templates` for the `primary_muscle_group` field.
