# Check audit: placement, carrying a flag, and saying the opposite

Date: 2026-10-07. Branch `claude/funny-cori-evrx1v`, started from `main` at `b9dfa37` (version 0.2.0 with the README update). Offline only: no model call, no Hevy pull, no stored output read.

## What prompted it

A review of the repository built a review by hand for the planted bench stall that put the bench in concerns and said it "is progressing normally and is not stalled", and showed it passing all twelve code checks. Two checks were named for meaning but measured placement: `story_found` matched the section and the exercise, and `flags_in_concerns` matched the exercise. Both also passed when there was nothing to test. In the latest run that was 9 of the 48 `story_found` passes (the negative cases) and 21 of the 48 `flags_in_concerns` passes (weeks without flags).

## What changed

- `story_found` is `expected_placement`, named for what it measures, and n/a on a negative case.
- `flags_in_concerns` is replaced by `flags_carried`, where a concern states the flagged condition, and `flags_consistent`, where no highlight or concern says the opposite. Thirteen code checks, eleven on real weeks.
- `coach.evals.flag_text` reads the prose for both, by word families with negation. `docs/checks.md` gives the rules and the limits.
- A check with nothing to test reports n/a. The harness, the report, `coach rescore` and `review.md` count n/a apart from passes, and the eval report has a row for negative cases.
- `docs/checks.md` gives one line per check on what it measures and what it does not. The README, the architecture note and the findings log label every past figure with the definition it was measured under.
- Tests: 41 in `tests/test_eval_flag_checks.py`, 210 in total.

## Decisions and rejected alternatives

- **Read the prose in code, narrowly, rather than change the schema.** A flag identifier in each finding, or flag sentences rendered by code, would change what the reviewer model is asked to produce, and no offline test can validate that. An identifier alone would also leave the prose beside it free to contradict it. The narrow reader leaves the reviewer exactly as it was and can be tested offline. Its cost is that it reads words, not meaning, and the limits are written down and pinned in tests.
- **Three checks, not one stronger check.** Placement, carrying the flag and consistency with it fail for different reasons and need different fixes, so a single verdict would hide which one failed. The audit's fixture now shows all three: placed, not carried, contradicted.
- **n/a rather than a pass.** A negative case cannot find a planted story, because there is none. Counting it as a pass inflated the placement rate. Its real result is `no_false_alarm`, which now has its own row.
- **A finding that says both is not carrying the flag.** "All three sessions done; none missed" mentions sessions, but it is not a statement that sessions were missed.
- **Earlier weeks and wishes are not claims.** "After steady progress earlier" and "needs to progress" were the first false alarms found when testing correct paraphrases. "Improved last week" still counts, because last week is the current story.
- **Do not re-score the stored runs in this change.** That work was deliberately left out, so this change reads no stored outputs. Until a re-score or a new run, the new checks have no numbers on model output, and the documents say so instead of estimating.

## Interviewer questions

1. Why read prose with word lists instead of asking a second model? Because the failure was in the checks, which should be cheap, deterministic and testable offline. A model grader already exists for meaning. What was missing was a deterministic floor under the two most important claims: the flagged condition is stated, and its opposite is not. The word lists are that floor, with known holes.
2. How do you know the reader does not fail correct reviews? Not yet from model output. The tests cover the paraphrases written for them, including the rising-effort story, where "RPE rising" beside an unchanged top set is correct. The next step is to re-score the stored reviews and read every failure before trusting the new rates.
3. What is the difference between schema validity, a number appearing, attribution and meaning? Schema validity says the review has the right shape. A number appearing says it exists somewhere in the data. Attribution says it belongs to the exercise, metric and week it is quoted for. Meaning says the sentence around it is true. This project now checks the first two, the third for percentages and partly for flags, and the fourth for flagged conditions only.
