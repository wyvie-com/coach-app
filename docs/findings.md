# Findings

One entry per real failure: when, which model, what the review got wrong, what was added (a check, a case or a prompt rule), and the pass rate before and after. Aggregates only; no set data and no review text from a real week. Dollar figures are what the runs cost on the day. The default review model throughout is `claude-haiku-4-5-20251001`; the grader is the same model with extended thinking.

Credit note: the Anthropic account's prepaid credit ran out on 2026-10-05 during the second full eval run (20 of 45 trials completed) and the hold re-run (5 of 9). Entries below say which numbers are partial. Total recorded spend on the project to that point: $5.00.

## 1. Grounding check too strict (eval, 2026-10-05)

- **Model:** Haiku 4.5 and Sonnet 5.5.
- **What went wrong:** `kg_grounded` failed 15 of 45 Haiku trials and 4 of 45 Sonnet trials. Almost every flagged number was 2.5, 5 or 7.5 kg: a load step the model had computed from two figures that were both in the tool result ("up 2.5 kg a fortnight"). None was invented.
- **What changed:** the check now accepts the absolute difference between two grounded figures for the same exercise. Differences across exercises still fail. `coach rescore` re-runs the checks over a stored run.
- **Before and after:** on the 20 stored reviews of the second run, strict 35% (7/20), refined 100% (20/20), same reviews. First run, strict: Haiku 67%, Sonnet 91%; those reviews were not stored, so they cannot be re-scored.

## 2. Haiku did not call a five-week bench stall a stall (eval, 2026-10-05)

- **Model:** Haiku 4.5.
- **What went wrong:** `story_found` failed 6 of 45 trials, all the same story: the bench top set unchanged for five weeks, which Haiku described as steady. Sonnet filed it as a concern in 45 of 45.
- **What changed:** the prompt defines progressing, stalled (top set unchanged for four or more consecutive weeks) and regressing.
- **Before and after:** bench stall cases, Haiku: before 3 of 6 trials; after 6 of 6 (second run, partial). Across the 20 trials that ran, `story_found` went from 87% (first run, all cases) to 100%; the cases not reached (missed sessions, deadlift regression, combined, the negatives) were at 100% before, so the comparison is on the cases that moved.

## 3. Grader hit its token ceiling (eval, 2026-10-05)

- **Model:** grader, Haiku 4.5 with `budget_tokens` 1,024.
- **What went wrong:** 7 of 90 grades ended in `max_tokens` at a 4,096 ceiling. The thinking budget is a target, not a cap (extended thinking page), and the overrun was large.
- **What changed:** `max_tokens` 8,192 for the grader.
- **Before and after:** 7 of 90 grades lost; then 0 of 20 (second run) and 0 of 8 (hold runs).

## 4. A two-week hold called a stall (real week 2026-W38)

- **Model:** Haiku 4.5.
- **What went wrong:** a lift whose top set was unchanged for two consecutive weeks was placed in concerns as "stalled", with the four-week definition already in the prompt. The data checks passed: every figure was real and the tool had been called. Only a reader could tell the finding was wrong.
- **What changed:** a negative case, `negative_two_week_hold`, in which every lift's review-week top set repeats the previous week's after a rise. Then a prompt sentence saying a two or three week hold is normal programming. That sentence was withdrawn the same day: with it, the planted bench stall was found in 3 of 5 trials, down from 6 of 6 without it. Replaced by a code-computed figure, `top_set_unchanged_weeks` in the tool result, and a prompt rule that four or more is a stall and one to three is not, so the model reads a count instead of making one.
- **Before and after:** `negative_two_week_hold`, Haiku, with the definition only: 0 of 3 (every trial raised concerns on every lift). With the count in the tool result: not yet measured; credit ran out. The real-week rate before was 1 of 4 weeks wrong.

## 5. A sessions concern below the stated threshold (real week 2026-W39)

- **Model:** Haiku 4.5.
- **What went wrong:** an "Overall" concern reported 0.75 of a missed session, although prompt rule 9 says to report sessions missed only at 1.0 or more. Again every figure was real.
- **What changed:** a data check, `sessions_threshold`, that fails an Overall concern mentioning sessions when `sessions_missed` is under 1.0. It runs on every real review and in the eval suite.
- **Before and after:** real weeks: 1 of 4 failed (W39) under the new check. Eval, second run: 20 of 20 passed. The prompt rule is unchanged; the check now enforces it.

## Trial variation

First full run, Haiku, three trials per case: `story_found` passed in every trial for 12 of 15 cases and in some trials for the other 3 (the bench stall cases); `kg_grounded` (strict) was stable in only 6 of 15 cases, which is what pointed at the check rather than the model. The grader's `follows_from_data` had the widest spread of the four dimensions (standard deviation 1.17 on Haiku's reviews, 0.74 on Sonnet's) and scored three quiet-week reviews at 2, so the grader and the code checks disagree about what a quiet week deserves; its reasons are now stored per trial for the next run to read.

## Not yet done

A full run with the unchanged-weeks count in the tool (entries 2 and 4), a run of `negative_two_week_hold` after it, and a Sonnet-graded comparison. Each needs credit on the account first; the full Haiku run is about $1.90 at the second run's $0.0425 per trial.
