# Architecture

How Coach integrates a language model into a data pipeline, and the trade-offs behind each choice. Numbers are from the runs recorded in `docs/notes/` and `docs/findings.md`.

## The shape of it

```
Hevy API ──pull──▶ private/hevy/<date>/*.json      raw pages, verbatim, gitignored
                        │
                   hevy/models.py                    validated raw shapes (strict where used, tolerant elsewhere)
                        │
                    model.py                         internal Workout / Exercise / Set, Melbourne ISO weeks
                        │
                   figures.py                        every number: volume, top set, e1RM (≤10 reps), rep PR,
                        │                            sessions baseline, 1 to 12 week history
                        ▼
   ┌─────────── review/loop.py ───────────┐
   │ system prompt (cached) + tool (strict) │◀──── exercise_history(exercise, weeks) answered from figures.py
   │ user turn: figures JSON (cached)       │
   │ loop: send → stop_reason → tool/parse  │────▶ Claude (Haiku 4.5 default; --model)
   │ structured output → Pydantic Review    │
   └───────────────────────────────────────┘
                        │
                 out/<week>/                         review, figures, run, cost, checks (gitignored)

   evals/cases.py ──▶ synthetic Hevy JSON ──▶ same path ──▶ checks.py (code) ──▶ grader.py (model) ──▶ report
```

The model never sees a raw workout. It sees numbers that code computed, it may ask for one exercise's history, and it returns JSON that a schema constrained and Pydantic validated. Every figure it quotes can be checked against the data by code, and is.

## Request shape

One request, repeated until the model stops calling the tool or a cap of eight turns is reached:

```json
{
  "model": "claude-haiku-4-5-20251001",
  "max_tokens": 4096,
  "system": [{"type": "text", "text": "<stable prompt>", "cache_control": {"type": "ephemeral"}}],
  "tools": [{"name": "exercise_history", "strict": true, "input_schema": {"...": "weeks is an integer enum 1 to 12"}}],
  "tool_choice": {"type": "auto", "disable_parallel_tool_use": true},
  "output_config": {"format": {"type": "json_schema", "schema": {"...": "headline, highlights, concerns, suggestions"}}},
  "messages": [
    {"role": "user", "content": [
      {"type": "text", "text": "<figures JSON>", "cache_control": {"type": "ephemeral"}},
      {"type": "text", "text": "Review ISO week 2026-W40."}
    ]}
  ]
}
```

The loop reads `stop_reason` before any content: `tool_use` runs the tool and appends a `tool_result` (with `is_error` when it failed); `pause_turn` sends the content back; `refusal`, `max_tokens` and `model_context_window_exceeded` end the run with that outcome; `end_turn` parses the text as JSON and validates it as a `Review`. Nothing is retried on content. Every outcome is written to `out/<week>/run.json`.

## Trade-offs considered

### A tool for history, or all history in the prompt

A year of this log is 611 workouts. Serialised as figures per exercise per week it would be tens of thousands of tokens on every request, most of it irrelevant to the week under review, and the model would be asked to find trends by reading. The tool turns that into a question the model asks when it needs to: "show me bench for eight weeks". It also gives the eval suite something to check: a concern about an exercise with no tool call for it is a judgement made without looking, and the `concern_preceded_by_tool` check fails it. In 90 synthetic trials and 4 real weeks that check has never failed, which says the instruction is followed. The cost is latency: a review is two to seven requests rather than one, 7 to 13 seconds on Haiku.

### Structured output, or free text

Free text would need a parser, and a parser would need a retry when the text did not parse. With `output_config.format` the API constrains generation to the schema, so invalid JSON has not occurred in 94 live reviews. The schema cannot express everything (`maxItems` is unsupported), so Pydantic validates again and enforces the three-suggestion cap. Two validations are a feature: the code shows which guarantee comes from where.

### Haiku by default, or a larger model

| | Haiku 4.5 | Sonnet 5.5 |
| --- | --- | --- |
| planted story found | 87% | 100% |
| kg figures grounded (strict check) | 67% | 91% |
| every other check | 100% | 100% |
| rubric follows_from_data (1 to 5) | 3.47 ± 1.17 | 3.55 ± 0.74 |
| review cost | $0.018 | $0.033 |
| seconds | 30 | 40 |

Haiku's only systematic miss was a five-week bench stall it called "steady". With the prompt defining "stalled", Haiku found it in 6 of 6 trials (second run, partial); the code now also hands the model the count of unchanged weeks so it reads a number instead of estimating one. Sonnet is 1.8 times the price and was never wrong on the synthetic stories. For a personal tool run once a week the difference is four cents a month, so cost is not the deciding factor; the deciding factor is that the eval suite exists to measure the gap rather than assume it, and the default should be the model whose weaknesses the checks can catch. Haiku's can. A real deployment would pick per the table, not per taste.

### A cheaper grader, or a stronger one

The grader is Haiku by default because the brief fixed that, with `--grader-model` for a different one. The evaluation guide prefers a grader that is not the generator. The grader's `follows_from_data` dimension has the widest spread of the four (std 1.17 on Haiku's reviews) and disagreed with the code checks on the quiet negative case three times out of three. A Sonnet-graded run is a one-flag experiment and belongs in the findings log when there is a question only it can answer.

### Caching boundaries

Order is tools, then system, then messages, and a prefix caches only from a breakpoint back. Haiku 4.5 needs 4,096 tokens before anything caches; the stable prefix here is smaller, so the first live run cached nothing. The week's figures are about 6,000 tokens and are re-sent on every tool round trip, so the second breakpoint sits after them: the first request writes the entry, the next ones read it. Measured: cost per review fell from $0.030 to $0.015 and time from 17 to 8 seconds. The lesson is that the caching boundary follows what is stable within a run, not what is stable across runs.

### A thousand users

Nothing in the loop is per-user state, so it scales horizontally. What would change: the pull would move to `GET /v1/workouts/events?since=` for incremental sync; reviews would run through the Message Batches API at half price with no latency requirement; the cache would stop paying because each user's figures are different and the shared prefix is under Haiku's minimum, unless the system prompt grew; the pricing table would come from a service rather than a file; and the eval suite would run on every prompt change in CI against stored reviews, with the paid run gated behind a manual approval.

### An agent framework, or a hand-written loop

The Tool Runner in the SDK, or the Claude Agent SDK, would have written the loop for me: tool dispatch, result formatting, retries. What they would have cost here is visibility. The point of this repository is that a reader can see where the stop reason is read, where a tool error becomes an `is_error` result, where the schema is validated the second time and why, and where cost is computed. That is about sixty lines in `review/loop.py`. A framework would have hidden them behind a `run()` call and added a dependency whose version drift the project would then track. For one tool and one output schema, the hand-written loop is the right size. At ten tools with approval gates and compaction, it would not be, and the Tool Runner's per-turn hooks would earn their place.

## Secrets and data boundary

Two credential routes, because the environments differ:

- **Anthropic.** The key is read from `COACH_ANTHROPIC_API_KEY` (falling back to `ANTHROPIC_API_KEY`) in one module, wrapped in a `Secret` that redacts itself, and passed to the SDK client as `api_key=`. The error for a missing key names the variable. The key lives in a Console workspace of its own with a monthly spend limit, so a runaway loop stops at the limit rather than at the credit card.
- **Hevy.** When `HEVY_API_KEY` is set it is sent. When it is not, the client sends the placeholder `proxy-injected` in the `api-key` header and the platform's egress proxy replaces it after the request leaves the session. The code never holds the Hevy key at all in that mode. Only the route name is ever recorded. A 401 on the proxy route means the proxy is not configured, and the error says so.

Why they differ: the Anthropic key must be in the process because the SDK signs requests with it; the Hevy key need not be, because the proxy can add a header. The second route is the better one and is used wherever the platform offers it.

What an enterprise deployment would use instead: a secret manager with workload identity (the process authenticates as itself and fetches the key at start, nothing in environment variables), or a gateway that holds the provider key and authenticates callers, so no application process ever sees it. The proxy route here is a small version of the gateway pattern.

Data: raw pages under `private/`, every run output under `out/`, both gitignored. Fixtures are generated by a committed script and contain no real values. gitleaks runs before every commit and over the whole history in CI. `docs/findings.md` carries aggregates only. Workout notes and descriptions are never read into the figures; titles are, truncated, because "Deload" is a signal.
