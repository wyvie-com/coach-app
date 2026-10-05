# Slice 2: figures

Date: 2026-10-05. Branch `claude/funny-cori-evrx1v`.

## What was built

- `coach.model`: the internal model. `WeekId` (parse, format, shift, Monday), `SetKind` (Hevy's four types plus `OTHER` with the original text kept), `Set`, `Exercise`, `Workout`. A workout's week is the ISO week of its start date in `Australia/Melbourne`; `from_raw_pages` converts validated Hevy pages, drops duplicate ids and sorts by start.
- `coach.figures`: pure functions to Pydantic models. `week_figures` gives sessions, the four-week sessions baseline, missed sessions, session titles, and per exercise: sessions, working and warm-up and other sets, volume, top set, Epley e1RM, mean RPE, superset flag, and the four-week e1RM change. `exercise_history` gives one entry per week over a 1 to 12 week window with empty weeks kept, plus first-to-last e1RM and RPE changes; it is the backend of the slice 3 tool. `format_table` renders the terminal table.
- `coach.evals.cases`: the planted-story generator. Fifteen cases (six stories with two seeds, combined, and two negatives), each thirteen weeks of three sessions emitted in Hevy's JSON shape and run through the raw models, so synthetic data travels the same path as real data. Each case carries its expectations (section and exercise) for slice 4.
- `coach figures --week 2026-W40 [--dry-run]`: loads the latest pull, prints the table and the JSON. No model call; the flag is accepted for symmetry with the brief.
- Tests: 79 passed in total. Model: week parsing and shifting across a 53-week year, Melbourne midnight versus UTC date, set kinds, superset flag, sorting and de-duplication. Figures: Epley, warm-up and null exclusion, the top-set tie rule, grouping by template id with title drift, the baseline with four, fewer than four, an empty and no prior weeks, windows of 1 and 12, empty-week entries, window bounds, unknown names, the four-week change. Stories: every planted story asserted visible in the figures by code alone, both negatives asserted quiet.

## Rules written down (also in the module docstrings)

- Working set: any set that is not a warm-up. Drop sets and failure sets count.
- Volume: weight times reps over working sets with both present.
- Top set: heaviest working set; ties to more reps, then to higher RPE.
- e1RM: Epley `w * (1 + reps / 30)` over working sets, best of the week; one rep is its own max.
- Sessions baseline: mean of the four prior weeks, an empty week counts as zero, weeks before the first workout in the data are not counted; None with no prior data.
- Four-week change: against the week four weeks earlier, else the earliest week in that window with data.
- Titles are carried over (truncated to 60 characters) because "Deload" is a signal; notes and descriptions are never read.

## Live dry run

`uv run coach figures --week 2026-W40 --dry-run` on the 2026-10-05 pull: 611 workouts spanning 2024-W16 to 2026-W40, 125 weeks with sessions. Week 40 had 4 sessions against a baseline of 3.00, 30 exercises, no warnings. Two findings for the record, aggregate only:

1. **No RPE anywhere.** Every `mean_rpe` is None. The `rising_rpe` story can never occur in my real data, and the review prompt must treat a missing RPE as "not recorded", never as a problem. This goes into the slice 3 prompt rules and the slice 4 checks.
2. **Epley at high reps.** Most working sets are 12 to 20 reps. Epley is calibrated for low reps and overstates badly above ten; the week's largest e1RM figure is a machine calf press that no one would call a one-rep max. The brief fixes Epley, so it stays, but the review prompt will describe e1RM as a comparison index rather than a lift the athlete could do, and a rep ceiling or a different formula is in `docs/later.md`. This is a question for the gate.

## Decisions and rejected alternatives

- **Group by template id, display the latest title.** Hevy lets a title be edited; the id is stable. Rejected: grouping by title, which would split a renamed exercise into two trends.
- **Keep empty weeks in a history window.** A stall (same load every week) and a gap (no sessions) must look different to the model and to the checks. Rejected: returning only weeks with data.
- **Baseline counts an empty week as zero but not weeks before the data starts.** Otherwise a new account would show four missed sessions in week two. Rejected: a fixed four-week mean that ignores the data start.
- **Synthetic cases emitted as Hevy JSON, not as internal objects.** It costs a few lines and proves the raw-to-internal path on every test run. Rejected: building `Workout` objects directly in the generator.
- **Four-week change in the week figures.** The tool exists for history, but one compact per-exercise delta lets the model decide which exercises are worth a call. Rejected: putting a 12-week series for every exercise in the user turn, which would be 30 exercises times 12 weeks of numbers each week.
- **Pydantic for the figure models, dataclasses for the internal model.** The figures are serialised to JSON for the model and validated against by the checks; the internal model is only ever in memory.

## How to run it

```
uv run pytest
uv run coach figures --week 2026-W40 --dry-run
uv run coach figures                      # last complete ISO week
uv run python -c "from coach.evals.cases import CASES; print([c.name for c in CASES])"
```

## What it does not do yet

No model call, no review, no cost. No e1RM alternative for high reps. No muscle-group grouping (needs exercise templates). The planted-story generator has no RPE-free variant yet, which slice 4 will need because the real data has none.

## Three questions an interviewer might ask

1. Why does an empty week inside the data count as zero sessions but a week before the first workout does not? Because the first is evidence of a missed week and the second is absence of evidence. A new account would otherwise start life with "four sessions missed" in its second week, which is a false alarm the negatives are designed to catch.
2. The synthetic logs are built as Hevy JSON and pushed through the raw models. Why not construct the internal objects directly? Every test run then also exercises the conversion layer, and a schema change in Hevy that broke real pulls would break the eval cases on the same day, in CI, with no network.
3. Epley gives a 325 kg calf press. Is the figure wrong? The arithmetic is right and the formula is the one the brief specifies; the assumption behind it, low-rep sets, does not hold for this athlete. The figure is still useful as a week-to-week index for the same exercise, which is how the trend and the four-week change use it, but it must never be presented as a lift the athlete could perform. Naming that limit in the prompt and the design note is the honest fix; choosing a different formula is a product decision, so it is listed as a later idea and raised at the gate.
