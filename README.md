# Coach

**Status: in development.** Version 0.1.0 covers the full pipeline on one account; see `docs/later.md` for what is deliberately not built.

## For the reader with two minutes

**What it does.** Coach reads a training log from the Hevy API, computes the week's figures in code (volume, top sets, estimated one-rep maxes where they are meaningful, rep PRs at matched loads, sessions against a four-week baseline, per-exercise history), and asks Claude to write a short weekly review: what went well, what needs attention, what to change next week. The model interprets numbers it is given; it never computes or invents them. Before it may call a lift progressing, stalled or regressing it must look at that lift's history through one strict tool. Its answer is constrained to a JSON schema by the API and validated again locally.

**What it costs.** A review on Claude Haiku 4.5 costs between one and three cents and takes 7 to 13 seconds, measured on four real weeks. Two cache breakpoints halve the cost of the tool round trips. Claude Sonnet 5.5 costs 1.8 times as much per review.

**What the evals show.** Sixteen synthetic training logs with planted stories (a bench stall, a squat PR, rising effort at the same load, missed sessions, a regression, and three weeks where nothing is wrong) run through the same code path, three trials each. Code checks run first: story found in the right section, no false alarm, every exercise name real, every kilogram figure traceable to the data, every concern preceded by a history lookup, at most three suggestions, no sessions concern under one missed session, no ranking of exercises the figures do not support, every flag the code raised carried into concerns, every percentage the exercise's own, no deload claimed without a deload title. A separate model grades four rubric dimensions second. On the first full run Haiku found the planted story in 87 percent of trials and Sonnet in 100 percent; Haiku's one systematic miss was calling a five-week stall "steady". After the prompt defined a stall and the code returned the count of unchanged weeks, Haiku found it in 12 of 12 trials, and the whole suite went from 87 to 94 percent, then 96 with no false alarms once the figures carried the comparisons the model had been getting wrong, then 100 percent, 48 of 48, once the code wrote the week's summary and flags and the model was asked to copy them. The one check still failing is the one that catches "across the board" said of five lifts in six, 10 trials in 48. `docs/findings.md` records each change with the pass rate before and after, including one prompt change that was withdrawn because it measured worse. No review on either model refused, truncated or invented an exercise.

**What it must never do.** Print, log or commit a key: keys are read in one module, redacted everywhere, and a secret scanner runs before every commit and over the whole history in CI. Commit real data or run output: the raw pull and every review live under gitignored directories, fixtures are generated, and the findings log carries aggregates only. Retry a bad answer silently: a refusal, a truncation, invalid JSON or a schema failure is recorded as an outcome and becomes an eval case. Give medical, nutritional or injury advice, or treat a missing RPE or a deload week as a problem.

## For the engineer

**Architecture.** The text diagram, the request shape and every trade-off are in `docs/architecture.md`. In one line: Hevy JSON, validated; internal model with Melbourne ISO weeks; pure figure functions; a hand-written tool loop with a turn cap that reads the stop reason before any content; structured output validated twice; cost per request priced by the model that served it; an eval harness that runs the same path on synthetic logs.

```
src/coach/
  settings.py        the only reader of environment variables; Secret redacts itself
  credentials.py     one request per API, statuses and the Hevy route only
  hevy/              read-only client, raw Pydantic shapes, verbatim page store, coach pull
  model.py           Workout / Exercise / Set, ISO weeks in Australia/Melbourne
  figures.py         every number the review may quote
  review/            schema and tool definition, system prompt, client protocol, loop, output
  pricing.py         USD per million tokens with source and date; unknown model raises
  evals/             planted-story cases, code checks, rubric grader, harness, report, rescore
  cli.py             coach check-credentials | pull | figures | review | eval | rescore
```

**How to run.**

```
uv sync
uv run pytest                                   # 167 tests, no network, no key
cp .env.example .env                            # COACH_ANTHROPIC_API_KEY; HEVY_API_KEY or the proxy route
uv run coach check-credentials                  # two status codes, nothing else
uv run coach pull                               # private/hevy/<date>/
uv run coach figures --week 2026-W40 --dry-run  # no model call
uv run coach review  --week 2026-W40            # out/2026-W40/, about two cents on Haiku
uv run coach eval --trials 3                    # out/eval/<timestamp>/, about $1.20 on Haiku
uv run coach eval --model claude-haiku-4-5-20251001 --model claude-sonnet-5-5 --trials 3
uv run coach eval --trials 3 --batch              # same suite through Message Batches, about $0.65, half an hour
uv run coach rescore out/eval/<timestamp>/trials.jsonl --strict-grounding
```

`--model` and `COACH_MODEL` choose the review model; `--grader-model` the grader. The live sequence is in `docs/live-runs.md`.

**How to add a case.** Six steps, under ten minutes, in `docs/notes/slice-4.md`: name the failure, add a `Story` and its expectation, plant it in one `if` in `evals/cases.py`, assert it is visible in the figures by code alone, bump the case count, run the eval for that case. The two cases added from real failures so far are in `docs/findings.md`.

**Documents.** `docs/spec.md` is the design as approved, with every external claim cited to the Hevy OpenAPI document or a Claude docs page and labelled Official, Secondary or reasoning. `docs/notes/slice-N.md` records what each slice built, what it rejected, and three questions an interviewer might ask. `docs/findings.md` is the log of real failures with pass rates before and after.

Licence: MIT. Copyright Wyvie.
