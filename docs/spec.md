# Coach: a personal AI training coach on Hevy data

Specification, phase 1, written 2026-10-05 against the official documentation current on that date. Each external claim is labelled **Official** (from the cited page), **Secondary** (non-primary source) or **My reasoning** (design choice). Where the docs are silent that is said and the conservative option is taken.

Sources: Hevy, the OpenAPI 3.0.0 document (`info.version` 0.0.1) embedded in `https://api.hevyapp.com/docs/swagger-ui-init.js`, which the Swagger page at `https://api.hevyapp.com/docs/` renders, cited as "Hevy OpenAPI". Claude, pages under `https://platform.claude.com/docs/en/`, cited by path.

## 1. Problem and goal

My training history lives in Hevy and I review it by impression, which hides stalls and regressions until they are weeks old. Coach pulls the workouts, computes the week's figures in code, has Claude write a short review that only interprets those figures, and measures that review with an evaluation suite so prompt and model changes are judged by numbers.

## 2. Hevy API facts and the internal model

### 2.1 Facts (all **Official** from Hevy OpenAPI unless marked)

- Host `https://api.hevyapp.com`. Every operation requires header `api-key` (string, format uuid). The document has no `servers` and no `securitySchemes` block, so the host is taken from the docs URL (**My reasoning**).
- `GET /v1/workouts` returns `{page, page_count, workouts[]}`; query `page` (default 1, "Must be 1 or greater") and `pageSize` (default 5, "Max 10"); 400 is "Invalid page size". `GET /v1/workouts/count` returns `{workout_count}`. `GET /v1/workouts/events?since&page&pageSize` returns `{type: "updated", workout}` or `{type: "deleted", id, deleted_at}` events "ordered from newest to oldest", `pageSize` max 10.
- `GET /v1/exercise_templates` returns `{page, page_count, exercise_templates[]}`, `pageSize` max 100. `GET /v1/exercise_history/{exerciseTemplateId}?start_date&end_date` returns flattened sets. `GET /v1/user/info` returns `{data: {weight_unit: "kg" | "lbs", ...}}`, "Defaults to kg if unset".
- Workout: `id, title, routine_id, description, start_time, end_time, updated_at, created_at` (ISO 8601 strings, examples end in `Z`), `exercises[]`. Exercise: `index, title, notes, exercise_template_id, superset_id` (number, nullable, "null indicates the exercise is not part of a superset"), `sets[]`. Set: `index, type, weight_kg, reps, distance_meters, duration_seconds, rpe, custom_metric`, all numeric fields nullable. Set `type` "can be one of 'normal', 'warmup', 'dropset', 'failure'"; the write-side `PostWorkoutsRequestSet` lists the same four as an enum and `rpe` as an enum of 6, 7, 7.5, 8, 8.5, 9, 9.5, 10. Weight is `weight_kg` only.
- No rate limit, no 429 and no `Retry-After` appear anywhere. The only guidance is `info.description`: "please don't send your requests exactly at xx:00. Put some random minute instead." Documented codes across the document: 200, 201, 400, 403, 404, 409, 500. 401 is undocumented. Ordering of `/v1/workouts` is undocumented. The API "is only available to Hevy Pro users" and Hevy "make no guarantees that we won't completely change the structure or abandon the project entirely".
- **Secondary** (my observation of 2026-09-29, not a documented guarantee): `GET /v1/workouts` with `api-key` returned 609 workouts at 10 per page.

Consequences (**My reasoning**): pagination by page number until `page == page_count`, 10 per page, about 61 requests for a full pull. No documented limit, so a polite 0.5 s interval between pages, `Retry-After` honoured if a 429 ever arrives, otherwise exponential backoff capped at 5 attempts. Any 401 is reported as "key rejected" with the active route named. Workouts are sorted by `start_time` in code and page order is never relied on.

### 2.2 Mapping to the internal model (**My reasoning** on each rule, **Official** on each source field)

| Internal | Source | Rule |
| --- | --- | --- |
| `Workout.start, end` | `start_time, end_time` | Timezone-aware datetimes; strings without an offset are rejected. |
| ISO week | `start_time` | Converted to `Australia/Melbourne` with `zoneinfo`, then `isocalendar()`. The API has no timezone field, so the zone is a constant. |
| `Exercise.name, template_id` | `title, exercise_template_id` | Title is the display name; template id is the join key across weeks because titles can be edited. |
| `Set.kind` | `type` | Enum `normal, warmup, dropset, failure`; unknown strings become `other` with a warning count, because the read schema gives the values in prose, not as an enum. |
| `Set.weight_kg, reps, rpe` | same | Nullable. Null weight or reps gives zero volume and no e1RM. |
| Warm-up | `type == "warmup"` | Excluded from volume, top set, e1RM and trend; counted as `warmup_sets`. |
| Superset | `superset_id` | A flag shown to the model; changes no figure. |
| Bodyweight, cardio | null weight or distance/duration set | Count as sets and sessions; excluded from kg figures. |
| Units | `weight_kg` | Always kg. `weight_unit` is read once for wording; nothing is converted. Notes and descriptions are never sent to the model. |

## 3. Architecture

Package `coach/`, one job per module, no agent framework.

| Module | Owns |
| --- | --- |
| `settings.py` | The only reader of environment variables. `COACH_ANTHROPIC_API_KEY` then `ANTHROPIC_API_KEY`; Hevy route `env` when `HEVY_API_KEY` is set, else `proxy`. Returns `Secret` objects with redacted `repr`. Missing key raises an error naming the variable. |
| `hevy/client.py` | Read-only `httpx` client: page iteration, timeouts, bounded retry on 429 and 5xx, `Retry-After`, polite interval, 401 to `HevyAuthError` naming the route; records `route` never the value. |
| `hevy/models.py` | Pydantic raw shapes, strict on the fields we use, `extra="allow"` for the rest. |
| `hevy/store.py` | Writes raw pages to `private/hevy/<date>/` plus a `manifest.json` of counts, route and docs date; reads them back. |
| `model.py` | Internal `Workout, Exercise, Set, SetKind` and the mapping in 2.2. |
| `figures.py` | Pure functions to `WeekFigures`: volume, top sets, Epley e1RM, trends over 1 to 12 weeks, sessions against the prior four-week mean. No I/O. |
| `review/schema.py` | The `Review` model, its JSON schema for `output_config.format`, and the `exercise_history` tool definition. |
| `review/prompt.py` | The stable system prompt constant and the per-week user turn renderer. |
| `review/loop.py` | The hand-written loop with a turn cap; returns a `ReviewRun` with every request's usage. |
| `review/client.py` | Builds the Anthropic client with `api_key=` explicit; a `ClaudeClient` protocol so tests inject a scripted fake. |
| `pricing.py` | Per-model prices with source URL and date; `cost(usage, model)`; unknown model raises. |
| `evals/cases.py, checks.py, grader.py, report.py` | Synthetic logs, code checks, rubric grader, report. |
| `cli.py` | `coach check-credentials, pull, figures, review, eval`. Prints counts and paths only. |

Flow: Hevy pages → `hevy/models` → `model` → `figures` → `review/prompt` → Claude → `review/schema` → `out/<week>/`. Evals swap in `evals/cases` and, in tests, the fake client.

## 4. The review

**Model.** Default `claude-haiku-4-5-20251001`. **Official:** the models overview lists it as current with alias `claude-haiku-4-5`, 200K context, 64K output, $1 in / $5 out per MTok, thinking "Extended", effort "Not supported", retirement not before 2026-10-15 (`/docs/en/about-claude/models/overview`, `/docs/en/models/haiku-4-5/overview`); it is in the structured outputs list of models supporting "both JSON outputs and strict tool use" (`/docs/en/build-with-claude/structured-outputs`). **My reasoning:** the pinned id is stored so pricing and findings refer to one snapshot; the alias is accepted and normalised. `--model` and `COACH_MODEL` override. Comparators with cited prices: `claude-sonnet-5-5` ($2 / $10) and `claude-opus-5-5` ($4 / $20) (**Official**, `/docs/en/about-claude/pricing`).

**Prompt.** System (stable, cached): role; rules (every kg figure copied from the data; call `exercise_history` before calling any lift progressing, stalled or regressing; at most three suggestions; exercise names exactly as in the figures or "Overall"; no nutrition or medical advice; say when nothing is wrong); definitions of volume, top set, Epley e1RM excluding warm-ups, trend windows and the sessions baseline; the four sections. User turn (per week): `WeekFigures` as compact JSON and "Review ISO week 2026-W40." Nothing time-varying sits in the system prompt or tool list.

**Tool.** One tool, `exercise_history(exercise: string, weeks: integer enum 1..12)`, `strict: true`, `additionalProperties: false`, both required. **Official:** `strict` is a top-level tool property; `minimum`/`maximum` are unsupported so the range is an integer `enum`, which is supported; names match `^[a-zA-Z0-9_-]{1,128}$`; descriptions should run to at least three or four sentences (`/docs/en/agents-and-tools/tool-use/strict-tool-use`, `/docs/en/build-with-claude/structured-outputs`, `/docs/en/agents-and-tools/tool-use/define-tools`). `tool_choice: {"type": "auto", "disable_parallel_tool_use": true}` for one call per turn (**Official**, `/docs/en/agents-and-tools/tool-use/overview`). **My reasoning:** the tool answers from the pulled local data, so a review has one network dependency and the eval harness answers it from synthetic logs. Result: per-week `{week, sessions, sets, top_set_kg, top_set_reps, e1rm_kg, mean_rpe}`; an unknown name returns `is_error: true` with the known names listed, following the advice to write "instructive error messages" (**Official**, `/docs/en/agents-and-tools/tool-use/handle-tool-calls`).

**Loop** (turn cap 8):

```
for turn in range(8):
    r = client.messages.create(model, system, tools, tool_choice, output_config, max_tokens=4096, messages)
    record usage, cost
    if r.stop_reason == "refusal":    return run("refusal", stop_details=r.stop_details)
    if r.stop_reason == "max_tokens": return run("max_tokens")
    append r.content verbatim
    if r.stop_reason == "pause_turn": continue
    if r.stop_reason == "tool_use":   append tool_result per tool_use block (is_error on failure); continue
    text = the text block; parse JSON; Review.model_validate
    return run("ok" | "invalid_json" | "schema_invalid", raw=text)
return run("turn_cap")
```

**Official:** stop reasons `end_turn, max_tokens, stop_sequence, tool_use, pause_turn, refusal, model_context_window_exceeded`, `stop_details` non-null only on refusal (`/docs/en/build-with-claude/handling-stop-reasons`); a refusal is HTTP 200 and "Output may not match your schema"; on `max_tokens` "Output is incomplete and may not match schema" (`/docs/en/build-with-claude/structured-outputs`); tool results come first in the next user message and immediately after the tool-use message (`/docs/en/agents-and-tools/tool-use/handle-tool-calls`). **My reasoning:** no content retry anywhere; every non-ok outcome is written to `out/<week>/run.json` with the raw text so it can become an eval case. The SDK's transport retries (2 by default on connection errors, 408, 409, 429, 5xx; **Official**, `/docs/en/cli-sdks-libraries/sdks/python`) stay on. No thinking on the review model: Haiku 4.5 "does not support interleaved thinking" (**Official**, `/docs/en/build-with-claude/thinking`) and low output cost is the point of the default.

**Schema.** `output_config.format = {"type": "json_schema", "schema": ...}` on `messages.create`, then `Review.model_validate_json`. `Review{headline: str, highlights: list[Finding], concerns: list[Finding], suggestions: list[Finding]}`, `Finding{exercise: str, text: str}`. **Official:** no beta header; `output_format` is deprecated for `output_config.format`; `additionalProperties: false` on every object; `minItems` only 0 or 1 and "Array constraints beyond minItems of 0 or 1" are unsupported; changing the format invalidates the cache; the SDK offers `messages.parse(output_format=Model)` (`/docs/en/build-with-claude/structured-outputs`). **My reasoning:** "at most three suggestions" therefore cannot be in the API schema; the prompt states it, Pydantic enforces `max_length=3`, a check counts it. `create` plus explicit Pydantic is used instead of `parse` so both steps are visible; `exercise` is a free string checked against the figures, not an enum, because names are data.

**Caching.** **Official:** order `tools` → `system` → `messages`; up to 4 breakpoints; `cache_control: {"type": "ephemeral"}` on the last tool or the system block; Haiku 4.5 minimum cacheable prefix 4,096 tokens, shorter prefixes "silently won't cache"; verify with `usage.cache_read_input_tokens`; writes 1.25× and reads 0.1× input (`/docs/en/build-with-claude/prompt-caching`, `/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching`). **My reasoning:** one breakpoint on the system block. The prefix may be under 4,096 tokens on Haiku; the first live run measures `cache_creation_input_tokens` and the result is reported as is, with what the same prefix would save on Sonnet 5.5 or Opus 5.5 (minimum 512, **Official**). The prompt is not padded to reach the minimum.

**Cost.** **Official:** `usage` has `input_tokens` (after the last breakpoint), `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `output_tokens_details.thinking_tokens` (`/docs/en/build-with-claude/prompt-caching`, `/docs/en/build-with-claude/thinking-steering-and-cost`). Prices per MTok on 2026-10-05 (input, 5 m write, 1 h write, read, output): Haiku 4.5 $1 / $1.25 / $2 / $0.10 / $5; Sonnet 5.5 $2 / $2.50 / $4 / $0.20 / $10; Opus 5.5 $4 / $5 / $8 / $0.20 / $20 (`/docs/en/about-claude/pricing`). **My reasoning:** cost is computed per request from `response.model`, summed per review, written to `out/<week>/cost.json`; a model missing from the table is an error.

## 5. Evals

**Cases.** Seeded eight-week synthetic logs, Melbourne timestamps, four barbell lifts and two accessories, three sessions a week, warm-ups included. Stories and expected placement: steady_progress (highlights, concerns empty); bench_stall (concerns, Bench Press (Barbell)); squat_pr (highlights, Squat (Barbell)); rising_rpe (concerns, Deadlift (Barbell)); missed_sessions (concerns, Overall); deadlift_regression (concerns, Deadlift (Barbell)); combined (bench_stall + squat_pr + missed_sessions); negative_quiet and negative_deload (loads down 10 %, RPE 6 to 7, titles contain "Deload"; concerns empty). Two seeds per single story, one each for combined and the negatives: 15 cases. **Official** guidance applied: "Prioritize volume over quality" and "factor in edge cases" (`/docs/en/test-and-evaluate/develop-tests`).

**Code checks** (first): `schema_valid`; `story_found` (expected section and exact exercise name); `no_false_alarm`; `exercises_exist`; `kg_grounded` (every "kg" number in headline, highlights, concerns matches a figure or a tool result to 0.5 kg); `concern_preceded_by_tool` (a successful `exercise_history` call for that exercise earlier in the run); `max_three_suggestions`.

**Rubric** (second, only on runs with a review). Grader `--grader-model`, default `claude-haiku-4-5-20251001`, sees figures and review, never the expected finding, returns four integers 1 to 5 (`follows_from_data, specific, safe, concise`) with one-sentence reasons through `output_config.format`. **Official:** use "a different model to evaluate than the model used to generate", 1 to 5 scales with defined ends, full context to the grader (`/docs/en/test-and-evaluate/develop-tests`). **My reasoning:** the default grader matches the brief; the report carries a `grader_model` column and one `--grader-model claude-sonnet-5-5` run reports agreement. **Thinking for the grader. Official:** Haiku 4.5 is extended-thinking only, `thinking: {"type": "enabled", "budget_tokens": N}`, N at least 1,024 and less than `max_tokens`, billed as output; thinking helps "complex tasks like math, coding, analysis" (`/docs/en/build-with-claude/extended-thinking`, `/docs/en/build-with-claude/thinking`). The docs say nothing about thinking combined with `output_config.format` and nothing specific to grading. **My reasoning:** start with thinking on at `budget_tokens: 1024`, `max_tokens: 2048`; if the first live grader call is rejected or returns no schema-valid text, fall back to thinking off and record which path ran. Grader `thinking_tokens` are costed like everything else.

**Trials and report.** `--trials 3`. Per check: pass rate over all trials and the count of cases passing in every trial. Rubric: mean and standard deviation. Plus mean tool calls, cost and seconds per review. `report.md` opens with one table, models as columns, Haiku first; `report.json` mirrors it; both under `out/eval/<timestamp>/`. Live runs refuse to start when the credential check fails; the harness runs offline against the fake in tests.

## 6. Live-run procedure and findings log

```
coach check-credentials                       # two status codes and the Hevy route, nothing else
coach pull                                    # private/hevy/<date>/, prints page and workout counts
coach figures --week 2026-W40 --dry-run
coach review --week 2026-W40 [--model ...]
coach eval --model claude-haiku-4-5-20251001 --trials 3
```

`docs/findings.md`: one entry per real failure with date, model, what the review got wrong (described, no set data), the check or case added, pass rate before and after, and trial variation. Aggregates only; raw outputs stay in `out/`.

## 7. Slices in build order (tests first in each)

| Slice | Builds | Tests |
| --- | --- | --- |
| 0 skeleton | uv, Python 3.12+, pytest, ruff; pre-commit with `astral-sh/ruff-pre-commit` (hooks `ruff-check`, `ruff-format`; latest `v0.16.10`, **Secondary**: GitHub releases) and `gitleaks/gitleaks` (hook `gitleaks`; latest `v8.30.1`, **Secondary**: GitHub releases, README shows the pre-commit form); `.gitignore` for `private/`, `out/`, `.env*`; `.env.example`; Actions running ruff, pytest, gitleaks; MIT licence; README; `coach check-credentials` (one `GET /v1/models`, **Official** `/docs/en/api/models/list`, and one `GET /v1/workouts/count`). | one trivial test; missing key error names the variable; `Secret` repr redacted; route selection with and without `HEVY_API_KEY`. |
| 1 Hevy client | `hevy/*`, `coach pull`; synthetic fixture pages with the docs date in `tests/fixtures/hevy/README.md`. | three-page pagination ends on `page_count`; 429 then 200 retried with backoff and `Retry-After`; 401 message names the route; page without `workouts` or with a non-ISO `start_time` rejected; key absent from logs and written files. Then a counts-only dry run on my account. |
| 2 figures | `model.py`, `figures.py`, `coach figures --week --dry-run`. | each planted story visible in the figures by code alone; Epley `w * (1 + reps / 30)`; warm-ups excluded; ISO week across a Melbourne midnight and a UTC date boundary; trend windows 1 and 12; sessions baseline with fewer than four prior weeks. |
| 3 review | `review/*`, `pricing.py`, `coach review`. | fake client: tool call then answer; refusal; max_tokens; invalid JSON; four suggestions rejected; `is_error` round trip; turn cap; cost with cache reads and writes; unknown model raises. |
| 4 evals | `evals/*`, `coach eval`. | each check on hand-built passing and failing reviews; harness offline end to end; Haiku first in the report; refuses live run without credentials. |
| 5 live runs and write-ups | `docs/live-runs.md`, four weeks of runs, `docs/findings.md`, two-audience README, `docs/architecture.md`, tag `v0.1.0`. | no new code paths; docs pass the secret scan. |
| 6 optional batch | `coach eval --batch`. **Official:** "All active models support the Message Batches API"; 50 % off; most batches finish within an hour, results kept 29 days; tool use and extended thinking allowed; `stream: true` not allowed (`/docs/en/build-with-claude/batch-processing`). | result parsing from a fixture, keyed by `custom_id`, order independent. |

## 8. Risks and open questions

| Risk or question | Recommended answer |
| --- | --- |
| Hevy may change or withdraw the API. | Store raw pages verbatim; tolerant models; docs date on the fixtures. |
| No documented Hevy rate limit. | 0.5 s between pages; backoff on 429 and 5xx, 5 attempts; honour `Retry-After`; never run on the hour. |
| 401 on the proxy route is undocumented. | Error text: "Hevy returned 401 using the proxy route (HEVY_API_KEY not set); the platform proxy is not injecting the api-key header." |
| Cached prefix may be under Haiku's 4,096-token minimum. | Measure on the first live run and report it; do not pad. |
| Three-suggestion cap not expressible in the API schema. | Prompt, Pydantic `max_length=3`, and a check. |
| Thinking with structured outputs undocumented. | Grader tries thinking on at the minimum budget, falls back to off on rejection, records the path. Review model: no thinking. |
| Grader equals generator. | Keep the brief's default; one Sonnet-graded run reports agreement. |
| Exercise title drift. | Group by `exercise_template_id`, display the latest title. |
| Time zone. | Constant `Australia/Melbourne`, tested at the UTC boundary; configurable later. |
| Prompt injection via Hevy text. | Tool results are numbers built by our code; notes and descriptions never reach the model. |
| Secrets in `out/` or fixtures. | Both directories gitignored; gitleaks pre-commit and CI; fixtures generated, never copied. |
| Trial variance hides regressions. | Report "passed in every trial" beside pass rate; three trials minimum. |

Nothing here blocks slice 0. One choice to confirm at the slice 3 gate: `claude-sonnet-5-5` as the main comparator with a single `claude-opus-5-5` run for the architecture note.

## 9. Out of scope

Writing to Hevy (the client is read-only). Routines, folders, body measurements. Programme generation. Multi-user operation, web UI, scheduling, notifications. Agent frameworks, the Tool Runner, the Claude Agent SDK. Adaptive thinking and effort, unsupported on Haiku 4.5 (**Official**). Anything in `docs/later.md`.
