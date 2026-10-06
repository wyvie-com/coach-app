# Coach

**Status: version 0.2.0, released.** It covers the full pipeline on one account. `docs/later.md` lists what is deliberately not built, and `docs/findings.md` the one open issue.

## For the reader with two minutes

**What it does.** Coach reads a training log from the Hevy API, computes the week's figures in code (volume, top sets, estimated one-rep maxes where they are meaningful, rep PRs at matched loads, sessions against a four-week baseline, per-exercise history), and asks Claude to write a short weekly review: what went well, what needs attention, what to change next week. The model interprets numbers it is given; it never computes or invents them. The code also flags the clear-cut concerns, such as a top set unchanged for four weeks, a four-week strength drop or a missed session, and writes the week's summary as sentences. The review must carry every flag into its concerns and copy, rather than compose, any claim that ranks the lifts or covers them all. Before it may call a lift progressing, stalled or regressing it must look at that lift's history through one strict tool. Its answer is constrained to a JSON schema by the API and validated again locally.

**What it costs.** A review on Claude Haiku 4.5 costs one to three cents and takes 7 to 14 seconds, measured on six reviews of real weeks. Two cache breakpoints halve the cost of the tool round trips. Claude Sonnet 5.5 costs 1.8 times as much per review. A full eval run of 48 trials, reviews and grading included, costs about $1.20 live, or $0.65 at half price through the Message Batches API in about 35 minutes.

**What the evals show.** Sixteen synthetic training logs with planted stories (a bench stall, a squat PR, rising effort at the same load, missed sessions, a regression, and three weeks where nothing is wrong) run through the same code path, three trials each. Twelve code checks run first, from "the planted story is in the right section" to "every percentage belongs to the lift it is quoted for". A separate model grades four rubric dimensions second. The latest run, on Haiku 4.5:

| Check | Trials passed |
| --- | --- |
| Planted story found, in the right section | 48 of 48 |
| No false alarm | 48 of 48 |
| Every kilogram and percentage traceable to the data | 48 of 48 |
| Every flag the code raised carried into concerns | 48 of 48 |
| Rankings of lifts match the figures | 38 of 48 |

It got there in steps. On the first run Haiku found 87 percent of the planted stories, calling a five-week stall "steady", while Sonnet 5.5 found them all. Haiku reached 94 percent once the code counted unchanged weeks, 96 with no false alarms once the figures carried that count for every lift and named the leader on each comparison, and 100 once the code wrote the week's summary and flags for the model to copy. `docs/findings.md` records each change with its pass rate before and after, including one prompt change that was withdrawn because it measured worse. The open issue is the last row: the review still says "across the board" when five lifts in six moved, or ranks the second-placed lift first. No review on either model refused, truncated or invented an exercise.

**What it must never do.** Print, log or commit a key: keys are read in one module, redacted everywhere, and a secret scanner runs before every commit and over the whole history in CI. Commit real data or run output: the raw pull and every review live under gitignored directories, fixtures are generated, and the findings log carries aggregates only. Retry a bad answer silently: a refusal, a truncation, invalid JSON or a schema failure is recorded as an outcome and becomes an eval case. Give medical, nutritional or injury advice, or treat a missing RPE or a deload week as a problem.

## For the engineer

**Architecture.** The text diagram, the request shape and every trade-off are in `docs/architecture.md`. In one line: Hevy JSON, validated; internal model with Melbourne ISO weeks; pure figure functions that also write the week's summary and flags; a hand-written tool loop with a turn cap that reads the stop reason before any content, driven live or through Message Batches; structured output validated twice; cost per request priced by the model that served it; an eval harness that runs the same path on synthetic logs.

```
src/coach/
  settings.py        the only reader of environment variables; Secret redacts itself
  credentials.py     one request per API, statuses and the Hevy route only
  hevy/              read-only client, raw Pydantic shapes, verbatim page store, coach pull
  model.py           Workout / Exercise / Set, ISO weeks in Australia/Melbourne
  figures.py         every number the review may quote, and the summary and flags it must carry
  review/            schema and tool definition, system prompt, client protocol, loop, output
  pricing.py         USD per million tokens with source and date; unknown model raises
  evals/             planted-story cases, code checks, grader, harness, batch runner, report, rescore
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
uv run coach eval --trials 3 --batch            # same suite through Message Batches, about $0.65 and 35 minutes
uv run coach rescore out/eval/<timestamp>/trials.jsonl --strict-grounding
```

`--model` and `COACH_MODEL` choose the review model; `--grader-model` the grader. The live sequence is in `docs/live-runs.md`.

**How to add a case.** Six steps, under ten minutes, in `docs/notes/slice-4.md`: name the failure, add a `Story` and its expectation, plant it in one `if` in `evals/cases.py`, assert it is visible in the figures by code alone, bump the case count, run the eval for that case. One case and one check have come from real failures so far; both are in `docs/findings.md`.

**Documents.** `docs/spec.md` is the design as approved, with every external claim cited to the Hevy OpenAPI document or a Claude docs page and labelled Official, Secondary or reasoning. `docs/notes/slice-N.md` records what each slice built, what it rejected, and three questions an interviewer might ask; `docs/notes/follow-up.md` covers the work after version 0.1.0. `docs/findings.md` is the log of real failures with pass rates before and after.

Licence: MIT. Copyright Wyvie.
