# Coach

**Status: version 0.3.1, a single-account personal tool.** It runs the full pipeline on one person's Hevy log; anything in these documents about many users is a proposal and says so. Version 0.3.0 added the check changes described in `docs/checks.md` to 0.2.0, and 0.3.1 fixes a reading error in them found on real weeks (`docs/findings.md` entry 14). `docs/later.md` lists what is deliberately not built.

## For the reader with two minutes

**What it does.** Coach reads a training log from the Hevy API, computes the week's figures in code (volume, top sets, estimated one-rep maxes where they are meaningful, rep PRs at matched loads, sessions against a four-week baseline, per-exercise history), and asks Claude to write a short weekly review: what went well, what needs attention, what to change next week. The design keeps the arithmetic in code: the model is given the figures and asked to copy them rather than work anything out, and code checks test what it quotes. Those checks have limits, listed in `docs/checks.md`, and the findings log records the model working out load steps itself and back-computing a figure that appears nowhere in the data. The code also flags the clear-cut concerns, such as a top set unchanged for four weeks, a four-week strength drop or a missed session, and writes the week's summary as sentences. The review is asked to carry every flag into its concerns and to copy, rather than compose, any claim that ranks the lifts or covers them all. Before it may call a lift progressing, stalled or regressing it must look at that lift's history through one strict tool. Its answer is constrained to a JSON schema by the API and validated again locally. A review can be valid for the API and the schema and still fail the quality checks: the checks report it beside the review, and nothing retries it.

**What it costs.** Ten Haiku 4.5 reviews of real weeks, from 2026-10-05 to 07, cost one to three cents each and took 7 to 24 seconds. On one week reviewed twice, with and without a cache breakpoint after the figures, the cost fell from $0.030 to $0.015. Sonnet 5.5 cost 1.8 times as much per review in the first eval run. A full eval run of 48 trials, reviewer and grader together, cost $0.64 and $0.66 the two times it ran through the Message Batches API at half price, taking 34 and 37 minutes; run live it is estimated at about $1.20.

**What the evals show, and what they do not.** Sixteen synthetic training logs, thirteen with a planted story (a bench stall, a squat PR, rising effort at the same load, missed sessions, a regression) and three negative cases where nothing is wrong, run through the same code path, three trials each. Thirteen code checks run first; `docs/checks.md` gives one line per check on what it measures and what it does not. A separate model grades four rubric dimensions second, and that grader has not been checked against human judgement.

The latest full run (Haiku 4.5, 2026-10-06, 48 trials) was scored with the checks as they stood that day. Each figure is a pass count under that check's definition, not an accuracy rate:

| Check, as defined on 2026-10-06 | What a pass meant | Result |
| --- | --- | --- |
| `story_found` | the expected exercise appeared in the expected section; negative cases passed by default | 39 of 39 positive-case trials, plus the 9 negative-case trials |
| `no_false_alarm` | no concern about an exercise on which nothing was planted | 48 of 48, of which 9 were negative-case trials |
| `kg_grounded` | every kilogram number quoted was within 0.5 kg of some computed value, whichever exercise it belonged to | 48 of 48 |
| `pct_grounded` | every percentage quoted was one of that exercise's figures, sign ignored | 48 of 48, re-scored after a sign fix to the check |
| `flags_in_concerns` | the flagged exercise appeared in concerns; the words were not read | 27 of 27 trials that had a flag; 21 trials had none |
| `comparisons_grounded` | rankings and "all" claims matched the leaders and counts the code computed | 38 of 48 |

None of those checks read what a finding said. A review built by hand that put the bench in concerns but called it "progressing normally and not stalled" passed all twelve; it is not model output. The checks now read the words for the flagged conditions (`flags_carried`, `flags_consistent`). They have been run on model output once, on four reviews of real weeks on 2026-10-07, and wrongly failed one correct concern: a reader bug, fixed in 0.3.1 (findings entry 14). The stored eval reviews have not been re-scored, so there is no suite pass rate for them.

The suite reached those numbers in steps, recorded in `docs/findings.md` with pass rates before and after, including one prompt change withdrawn because it measured worse. The steps are not a controlled comparison: the first run had 15 cases and 45 trials, the latest 16 cases and 48, and the checks, the prompt and the figures changed in between. The open issue is the last row: the review still says "across the board" when five lifts in six moved, or ranks the second-placed lift first. No review on either model refused, truncated or invented an exercise.

**Known limits.** The checks read words and numbers, not meaning:

- The flag checks read the highlights and concerns about a flagged exercise, by word families. They do not read the headline or suggestions, check the numbers inside a statement, or follow phrasing outside their word lists, and their false-failure rate on model prose is not yet measured: four real-week reviews are too few.
- Kilogram grounding accepts a real number attached to the wrong exercise, metric or week. Percentage grounding ignores the sign and the window. Neither reads suggestions.
- A rep PR, rising effort and steady progress are checked for placement only.
- Meaning beyond the code checks rests on the rubric grader, which is uncalibrated.
- `coach review` exits successfully even when a check fails.

**What it must never do.** Print, log or commit a key: keys are read in one module, redacted everywhere, and a secret scanner runs before every commit and over the whole history in CI. Commit real data or run output: the raw pull and every review live under gitignored directories, fixtures are generated, and the findings log carries aggregates only. Retry a bad answer silently: a refusal, a truncation, invalid JSON or a schema failure is recorded as an outcome, so it can be turned into an eval case. Give medical, nutritional or injury advice, or treat a missing RPE or a deload week as a problem: the prompt asks this of the model and the rubric scores it, and no code check enforces it.

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
  evals/             cases, code checks, flag reader, grader, harness, batch runner, report, rescore
  cli.py             coach check-credentials | pull | figures | review | eval | rescore
```

**How to run.**

```
uv sync
uv run pytest                                   # 224 tests, no network, no key
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

**Documents.** `docs/spec.md` is the design as approved, with every external claim cited to the Hevy OpenAPI document or a Claude docs page and labelled Official, Secondary or reasoning. `docs/notes/slice-N.md` records what each slice built, what it rejected, and three questions an interviewer might ask; `docs/notes/follow-up.md` covers the work after version 0.1.0. `docs/findings.md` is the log of real failures with pass rates before and after. `docs/checks.md` defines each code check and its limits, and `docs/notes/check-audit.md` records why the checks changed on 2026-10-07.

## Who did what

John ([@wyvie-com](https://github.com/wyvie-com)), the repository owner, set what the project had to be and decided between options. Claude, working in Claude Code, wrote the code, tests and documents and ran the evaluations. From the build conversation:

- **Requirements.** John supplied the brief: the problem, the rules (tests before code, no network in tests, how keys are read and never shown, the data boundary, CI, the default model), the evaluation approach of code checks first and a rubric second, and a build in slices that stopped for approval after each one.
- **Decisions.** John accepted Claude's recommendation of Sonnet 5.5 as the comparison model with one Opus run, and chose Wyvie as the copyright holder. John questioned an unsourced claim about estimated one-rep maxes and supplied sourced research, which set the ten-rep ceiling and rep PRs at matched loads. John also said deload weeks are part of the training being reviewed, which led to the deload rule.
- **Direction and acceptance.** John approved each slice, the paid work and its budget, asked for the push from 96 to 100 percent and for the comparison weakness to be fixed, approved the README update, published the v0.2.0 release, merged the first pull request, and brought the review that found the gap described in `docs/checks.md`.
- **Implementation.** Claude proposed most technical designs, among them the code-computed unchanged-weeks count, the code-written summary and flags, batch rounds and the narrow flag reader, and implemented all of them. John reviewed and accepted them.

Licence: MIT. Copyright Wyvie.
