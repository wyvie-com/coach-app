# Live runs

Everything here runs in a Claude Code cloud session with the two credential routes described in `docs/architecture.md`. Nothing here is run in CI, and nothing it writes is committed: `private/` holds the raw pull, `out/` holds every review and eval.

## The sequence

```
uv run coach check-credentials                 # two status codes and the Hevy route; stop if either is not 200
uv run coach pull                              # private/hevy/<date>/, prints counts only
uv run coach figures --week 2026-W40 --dry-run # table and JSON, no model call
uv run coach review  --week 2026-W40           # out/2026-W40/, prints the review, the run and the data checks
uv run coach eval --trials 3                   # out/eval/<timestamp>/, same model as the review by default
```

Run `review` once per week you want covered; `eval` once per prompt or model change. Add `--model claude-sonnet-5-5` to either for the comparison model, and `--model` twice to `eval` for a side-by-side report.

## What to look at afterwards

- `out/<week>/review.md`: the review, the run (turns, tool calls, cost, seconds) and the six data-bound checks.
- `out/<week>/run.json`: outcome, every request's usage, every tool call. A non-`ok` outcome is a finding.
- `out/eval/<timestamp>/report.md`: the summary table first. `trials.jsonl` has every trial with its review, so `coach rescore` can re-run changed checks for free.

## Rules

- Never schedule the pull on the hour; Hevy asks for a random minute.
- `private/` and `out/` live only in the session's container, which is wiped after a period of inactivity. Archive both after each live run (for example `tar -czf coach-data-<date>.tar.gz private out`) and keep the archive outside the repository; it holds personal data.
- Record failures in `docs/findings.md` as aggregates: date, model, what went wrong, what changed, pass rate before and after. No set data, no review text from a real week.
