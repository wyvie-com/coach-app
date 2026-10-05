# Slice 3: the review

Date: 2026-10-05. Branch `claude/funny-cori-evrx1v`.

## What was built

- `coach.pricing`: USD per million tokens for `claude-haiku-4-5-20251001`, `claude-sonnet-5-5` and `claude-opus-5-5` (input, 5 m cache write, 1 h cache write, cache read, output) with the source URL and the date read; alias `claude-haiku-4-5` resolves to the snapshot; `cost(usage, model)` prices one response from `input_tokens`, `cache_creation_input_tokens` (split by TTL when `cache_creation` is present), `cache_read_input_tokens` and `output_tokens`; an unknown model raises rather than pricing at zero.
- `coach.review.schema`: `Review` and `Finding` (extra keys forbidden, blank text rejected, at most three suggestions) and the JSON schema sent as `output_config.format`, which cannot carry the three-item cap and does not; the strict `exercise_history` tool definition with `weeks` as an integer enum 1 to 12; a `ToolInput` model that validates tool input locally too.
- `coach.review.prompt`: the system prompt as a constant with eleven numbered rules (copy kilogram figures, call the tool before judging a trend or raising a concern, exact names or "Overall", three suggestions, missing RPE is not a problem, e1RM is an index and only for ten reps or fewer, rep PR and "new" load, deload titles, sessions missed only at 1.0 or more, say when nothing is wrong, no medical advice) and the per-week user turn as two text blocks, figures then instruction.
- `coach.review.client`: a two-method protocol the loop depends on, and `build_client` which passes the key explicitly.
- `coach.review.loop`: the hand-written loop, turn cap 8, `max_tokens` 4096, no thinking. Stop reason is read before any content. Outcomes: `ok`, `refusal` (with `stop_details`), `max_tokens`, `context_exceeded`, `no_text`, `invalid_json`, `schema_invalid`, `turn_cap`. Tool errors (unknown tool, input outside the schema, unknown exercise) go back as `is_error` results with instructive text. Each request gets its own copy of the message list so a recorded request is a snapshot. Cost is priced per request from `response.model`.
- `coach.review.output`: `out/<week>/figures.json`, `review.json`, `run.json`, `cost.json`, `review.md`.
- `coach review --week W [--model M]`: loads the latest pull, runs the loop, writes the files, prints the review and the run summary. Exit code 1 for any outcome other than `ok`.
- Tests: 26 new, 110 in total, all against a scripted fake client that returns real SDK `Message` objects: tool call then answer (request shape asserted field by field), refusal, max_tokens, invalid JSON, four suggestions, unknown exercise round trip, out-of-schema tool input, unknown tool name, turn cap, pause_turn, cache usage into cost, pricing with and without cache fields and with a one-hour share, alias normalisation, unknown model, schema closure, output files.

## Live runs (Haiku 4.5, week 2026-W40, my data)

Credential check first: `anthropic 200`, `hevy 200 route=proxy`.

| Run | Breakpoints | Turns | Tool calls | Cache write / read tokens (request 1, then 2 to 4) | Cost | Seconds |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | system only | 4 | 3 | 0 / 0 on every request | $0.0296 | 16.8 |
| 2 | system and figures | 4 | 3 | 6,289 written, then 6,289 read three times | $0.0146 | 7.8 |

Run 1 confirmed the spec's prediction: tools plus system is under Haiku's 4,096-token minimum, so the system breakpoint alone caches nothing. The figures block is about 6,000 tokens and is re-sent on every tool round trip, so a breakpoint after it is the one that pays: input cost fell from $0.0274 to $0.0022 plus $0.0079 of cache write and $0.0019 of cache read.

Both reviews reached `ok`, called the tool three times (one call per turn, as instructed), named only exercises from the figures, and put the bench press in concerns after a tool call. Both quoted kilogram figures that appear in the data or the tool results. Observed weaknesses, for the eval suite rather than for this slice: run 2 praised a calf press for "returning to 20 reps" when the rep PR flag said no PR, which is grounded but thin; both runs raised a one-week dip in bench as a concern with a 4-week change of about minus 5 percent, which is arguable; the suggestions are generic. The rubric in slice 4 is what should judge those.

## Decisions and rejected alternatives

- **Two cache breakpoints, not one.** The brief asked for a cached system prompt and tool list with the figures in the user turn. Measured on Haiku, that caches nothing. Adding a breakpoint after the figures halves the cost and the latency of a multi-turn review without changing what the model sees. Rejected: padding the system prompt to 4,096 tokens, which would cost money to save money.
- **`create` plus Pydantic rather than `messages.parse`.** Both validation steps are visible in `loop.py`; the SDK helper would hide the second. Named as a teaching choice.
- **Tool input validated locally even with `strict: true`.** Strict mode should make it redundant; the test with `weeks: 40` shows the loop survives if it is not.
- **Tool results carry the history JSON, not prose.** The model copies numbers from a structure; prose would invite paraphrase.
- **Pricing by `response.model`, not the requested model.** The response says which snapshot served the request; an alias in the request is resolved by the API.
- **No content retries anywhere.** A refusal, a truncated answer, invalid JSON or a schema failure is written to `out/<week>/run.json` with the raw text. The eval suite will count them.
- **Snapshot of the message list per request.** Found by a test: the fake recorded a live list that grew after the request. Production would not have noticed; the record would have lied.

## How to run it

```
uv run pytest
uv run coach check-credentials
uv run coach review --week 2026-W40
uv run coach review --week 2026-W40 --model claude-sonnet-5-5
cat out/2026-W40/review.md
```

## What it does not do yet

No evaluation: nothing checks whether the review found the right thing. No grader. No comparison across models beyond running the command twice. No batch path. The prompt has not been tuned against anything; slice 4 provides the numbers to tune against.

## Three questions an interviewer might ask

1. Why read `stop_reason` before touching the content? Because a refusal and a `max_tokens` cut-off both return HTTP 200 with content that may look like a partial answer. Reading content first would parse a truncated JSON object or a refusal message as if it were the review. The docs say both may not match the schema, so the loop treats the stop reason as the verdict and the content as evidence.
2. The brief specified caching the system prompt and tools. Why did you add a second breakpoint? Because the first live run measured zero cache activity: Haiku's minimum cacheable prefix is 4,096 tokens and the stable prefix is smaller. The figures are stable within a run and about 6,000 tokens, so caching them is where the saving is. The brief's intent was to show the caching boundary; the measured result is a better demonstration than the assumed one, and the note records both numbers.
3. What does `strict: true` buy you if you validate the tool input again anyway? The guarantee that the input matches the schema comes from the API and removes a class of retries. The local validation is cheap insurance against the one case the guarantee does not cover, a different model or a future change, and it is the only place a bad input turns into an instructive `is_error` result rather than a crash.
