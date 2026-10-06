# Findings

One entry per real failure: when, which model, what the review got wrong, what was added (a check, a case or a prompt rule), and the pass rate before and after. Aggregates only; no set data and no review text from a real week. Dollar figures are what the runs cost on the day. The default review model throughout is `claude-haiku-4-5-20251001`; the grader is the same model with extended thinking.

Credit note: the Anthropic account's prepaid credit ran out on 2026-10-05 during the second full eval run (20 of 45 trials completed) and the hold re-run (5 of 9), at $5.00 of spend. After a $5 top-up the same day, a third full run (48 trials, $1.84), an Opus review of one real week ($0.11), a missed-sessions re-run ($0.17) and a Sonnet-graded run completed the measurements. The eval command now prints an estimate and takes a `--budget-usd` cap.

## 1. Grounding check too strict (eval, 2026-10-05)

- **Model:** Haiku 4.5 and Sonnet 5.5.
- **What went wrong:** `kg_grounded` failed 15 of 45 Haiku trials and 4 of 45 Sonnet trials. Almost every flagged number was 2.5, 5 or 7.5 kg: a load step the model had computed from two figures that were both in the tool result ("up 2.5 kg a fortnight"). None was invented.
- **What changed:** the check now accepts the absolute difference between two grounded figures for the same exercise. Differences across exercises still fail. `coach rescore` re-runs the checks over a stored run.
- **Before and after:** on the 20 stored reviews of the second run, strict 35% (7/20), refined 100% (20/20), same reviews. First run, strict: Haiku 67%, Sonnet 91%; those reviews were not stored, so they cannot be re-scored.

## 2. Haiku did not call a five-week bench stall a stall (eval, 2026-10-05)

- **Model:** Haiku 4.5.
- **What went wrong:** `story_found` failed 6 of 45 trials, all the same story: the bench top set unchanged for five weeks, which Haiku described as steady. Sonnet filed it as a concern in 45 of 45.
- **What changed:** the prompt defines progressing, stalled (top set unchanged for four or more consecutive weeks) and regressing.
- **Before and after:** bench stall cases, Haiku: before 3 of 6 trials; after 6 of 6 in the second run (partial) and 6 of 6 again in the third full run with the unchanged-weeks count in the tool result. `story_found` over the whole suite: 87% (first run) to 94% (third run, 16 cases, 48 trials); the three remaining misses were a different story, entry 6.

## 3. Grader hit its token ceiling (eval, 2026-10-05)

- **Model:** grader, Haiku 4.5 with `budget_tokens` 1,024.
- **What went wrong:** 7 of 90 grades ended in `max_tokens` at a 4,096 ceiling. The thinking budget is a target, not a cap (extended thinking page), and the overrun was large.
- **What changed:** `max_tokens` 8,192 for the grader.
- **Before and after:** 7 of 90 grades lost; then 0 of 20 (second run), 0 of 8 (hold runs), 0 of 48 (third run).

## 4. A two-week hold called a stall (real week 2026-W38)

- **Model:** Haiku 4.5.
- **What went wrong:** a lift whose top set was unchanged for two consecutive weeks was placed in concerns as "stalled", with the four-week definition already in the prompt. The data checks passed: every figure was real and the tool had been called. Only a reader could tell the finding was wrong.
- **What changed:** a negative case, `negative_two_week_hold`, in which every lift's review-week top set repeats the previous week's after a rise. Then a prompt sentence saying a two or three week hold is normal programming. That sentence was withdrawn the same day: with it, the planted bench stall was found in 3 of 5 trials, down from 6 of 6 without it. Replaced by a code-computed figure, `top_set_unchanged_weeks` in the tool result, and a prompt rule that four or more is a stall and one to three is not, so the model reads a count instead of making one.
- **Before and after:** `negative_two_week_hold`, Haiku, with the definition only: 0 of 3 (every trial raised concerns on every lift). With `top_set_unchanged_weeks` in the tool result and the prompt reading the count: 2 of 3 (third run); the one failure again raised concerns on every lift, so the count helps but does not settle it. The real-week rate before was 1 of 4 weeks wrong. This is the suite's open failure.

## 5. A sessions concern below the stated threshold (real week 2026-W39)

- **Model:** Haiku 4.5.
- **What went wrong:** an "Overall" concern reported 0.75 of a missed session, although prompt rule 9 says to report sessions missed only at 1.0 or more. Again every figure was real.
- **What changed:** a data check, `sessions_threshold`, that fails an Overall concern mentioning sessions when `sessions_missed` is under 1.0. It runs on every real review and in the eval suite.
- **Before and after:** real weeks: 1 of 4 failed (W39) under the new check. Eval: 20 of 20 (second run) and 48 of 48 (third run) passed. The prompt rule is unchanged; the check now enforces it.

## 6. Missed sessions noticed but filed outside concerns (eval, 2026-10-05)

- **Model:** Haiku 4.5.
- **What went wrong:** in the third full run, 3 of 6 missed-sessions trials failed `story_found`. Every one of those reviews stated that two sessions were missed, in the headline, a highlight or a suggestion, but not in concerns. Prompt rule 9 said to report it "under Overall" without naming the section.
- **What changed:** rule 9 now says a missed-sessions figure of 1.0 or more is a concern and belongs in concerns under "Overall".
- **Before and after:** missed-sessions cases, Haiku: 3 of 6, then 6 of 6 on a re-run of the two cases ($0.17).

## 7. One Opus review of a real week (2026-10-05)

- **Model:** Opus 5.5, week 2026-W40, the same week Haiku reviewed.
- **Result:** every data check passed; 5 turns, 4 tool calls, 24 seconds, $0.108 against Haiku's $0.026 for the same week. Opus raised three concerns where Haiku raised two, the third being a dumbbell press Haiku had passed over. Not a failure; recorded so the architecture note's model table has a measured Opus row.

## 8. The grader judged without the tool results (eval, 2026-10-05)

- **Model:** grader. Haiku 4.5 by default; Sonnet 5.5 for the comparison the architecture note asked for.
- **What went wrong:** the Sonnet grader scored Haiku's reviews at a mean `follows_from_data` of 1.66 out of 5 (32 trials) against the Haiku grader's 2.75 on the same cases. Its reasons said the reviews quoted "fabricated" eight-week gains. Those gains were in the exercise_history results the review had looked up, which the grader was never shown: it saw the week's figures and the review only. The lenient grader had hidden a flaw in the grading input; the stricter one exposed it.
- **What changed:** the harness recomputes each successful tool call's history and passes it to the grader with the figures and the review, which is also what the `kg_grounded` check uses.
- **Before and after:** Sonnet grader, `follows_from_data`, same prompt and cases: 1.66 (32 trials) to 3.00 (16 trials, one per case). Per story the rise was everywhere: bench stall 2.0 to 4.0, missed sessions 2.0 to 4.5, deload 2.5 to 4.0, steady progress 1.0 to 2.5. What remains at 2 to 3 is now real: a review that called one lift's growth the fastest when its own figures showed another grew faster; "lower volume" claimed for a deload week without a prior-week volume to compare. Those are the next prompt and figure changes, and the grader is now trustworthy enough to measure them.
- **Cheaper or stronger grader:** on these reviews Sonnet grades at about $0.016 per review against Haiku's $0.014 with thinking, so cost is not the difference. Sonnet's reasons were specific enough to debug the grader itself; Haiku's were not. The default stays Haiku because the brief set it, but the architecture note recommends Sonnet for the grader when the goal is to find out why.

## 9. The two-week hold, settled by moving the count into the figures (eval, 2026-10-06)

- **Model:** Haiku 4.5.
- **What went wrong:** entry 4's open failure. In 5 of 12 hold trials across the later runs the review put every lift in concerns as "stalled" or "flat for two weeks", despite the tool returning `top_set_unchanged_weeks` of 2 and the rule saying one to three is normal. The reviews' wording gave the mechanism away: "interrupting the progression pattern", "halting the steady weekly advances". The model had read the history, seen weekly rises, and treated the first week without one as the problem. The count was in the tool result, which the model only saw after it had decided which exercises to look up.
- **What changed:** `top_set_unchanged_weeks` is now computed for every exercise in the week's figures as well, over the prior twelve weeks, so the model sees the count before any tool call. One helper computes it in both places. Rule 2 now says that below four it is never a concern, whatever the earlier weeks looked like and however many exercises hold at once, and that weekly increases are not required.
- **Before and after:** `negative_two_week_hold`, Haiku: 2 of 3 (third run), 1 of 2 and 1 of 1 in the two Sonnet-graded runs, so 4 of 6 over the latest runs. After: 3 of 3, with the two bench stall cases run alongside as the regression guard: 6 of 6 `story_found`. Nine trials, $0.28. The real-week rate for this failure is not yet re-measured.

## 10. Rankings the figures did not support (eval, 2026-10-06)

- **Model:** Haiku 4.5, graded by Sonnet 5.5.
- **What went wrong:** the Sonnet grader's remaining criticisms (entry 8) fell into four kinds: an exercise called "fastest" or "largest" when another had the bigger figure (5 of 16 reviews); "all six exercises progressed" when one was flat (3 of 16); an eight-week change labelled four-week (2 of 16); "lower volume" or "strong volume" with no prior-week figure to compare. Every kilogram figure was real; the errors were in comparing six rows and in labelling windows, which the code checks did not cover.
- **What changed, in two passes.** First pass: `volume_prior_week_kg` and `volume_change_1w_pct` per exercise, and a rule on comparisons and windows. Code checks stayed at 16 of 16 and `follows_from_data` went 3.00 to 3.12, which is noise at n=16; the grader's reasons showed the same wrong superlatives. The prompt had asked Haiku to compare six rows and it still could not. Second pass: the figures now carry `leaders`, the exercise with the highest value on each comparable figure (null on a tie), and `counts`, how many exercises rose, held or fell; the rule says to rank only from leaders and to write "all" or "every" only when the count is full; and a new code check, `comparisons_grounded`, fails a superlative about an exercise that leads nothing, an "Overall" superlative that names no leader, and a universal claim of progress when the counts are short. Rescored offline over the two earlier Sonnet-graded runs, the check would have passed 9 of 16 and 11 of 16 reviews, every failure one the grader had also named.
- **Before and after:** `comparisons_grounded`, Haiku: 56% and 69% on the two stored runs, 75% (12 of 16) live after the second pass. By kind: wrong superlative 5 of 16 to 1 of 16; "all" or "across the board" with a short count 3 of 16 to 3 of 16 at first, then 1 of 5 on the affected cases after the rule named "across the board" and told the model to write "five of six" instead, which it then did, in the same sentence as the flourish. Tool calls per review fell from 2.06 to 1.12 and the review cost from $0.0156 to $0.0103, because the model has the comparison in front of it and looks less up. `follows_from_data` stayed at 3.12 (one trial per case, standard deviation 0.9, so a change under about 0.5 is not measurable at this size). The grader's remaining reasons are now figure mix-ups between the many similar percentages per exercise, which is the cost of adding fields; the next step would be fewer fields, not more.
- **Side effects seen once each, not yet reproduced:** a false alarm on the hold case filed under "Overall" ("progress has paused") and one invented starting e1RM (39.8 kg, back-computed from a percentage). Both are recorded in the trial files for the full run to count.

## 11. Fourth full run, on the final prompt, through batches (eval, 2026-10-06)

- **Model:** Haiku 4.5 reviews, Haiku 4.5 grader with thinking; 16 cases, 3 trials, through the Message Batches API.
- **Result against the third full run (2026-10-05, live, same cases):** `story_found` 94% to 96% (46 of 48; the two misses were one missed-sessions trial that filed the finding outside concerns and one combined trial that passed over the bench), `no_false_alarm` 94% to 100% (48 of 48, the hold case 3 of 3), `kg_grounded` 94% to 98% (one invented volume figure), everything else 100%. The new `comparisons_grounded` check, which the third run predates, passed 71% (34 of 48, stable in 7 of 16 cases). Rubric means on the Haiku grader, `follows_from_data` 4.38, `safe` 4.83, in line with the third run; the Haiku grader's ceiling (entry 3) still applies.
- **What the 14 comparison failures are:** 10 are "across the board" or "all five exercises" in an "Overall" finding when the counts say five of six; 4 are a superlative on Overhead Press ("largest", "fastest", "strongest") when Dumbbell Row leads on every figure and the leaders field says so. The model reads the leaders when it names the Row and ignores them when it reaches for a flourish about the whole week. A rule already forbids both; the next move is not another sentence of prompt.
- **Cost and time:** $0.64 for 48 trials against $1.84 live for the third run; review cost per review $0.0060 (half price, and 1.38 tool calls per review against 2.06 before the figures carried the comparisons). Six batches: five review rounds of 48, 47, 11, 7 and 1 requests, then one grading batch of 48; 34 minutes end to end, every request succeeded, the grader's thinking request accepted in the batch.
- **Side effects from entry 10, re-measured:** the "Overall" false alarm on the hold case did not recur (3 of 3 clean); the invented back-computed figure recurred once (1 of 48).

## 12. The code writes the summary; every planted story found (eval, 2026-10-06)

- **Model:** Haiku 4.5 reviews, Haiku 4.5 grader; 16 cases, 3 trials, batched. Fifth full run.
- **What went wrong before:** entry 11's two misses and its 14 comparison failures were one habit: a figure the model had, rewritten into a kinder or grander sentence. A one-session week became "a deload", a five-week stall "held steady", five lifts in six "across the board".
- **What changed:** the figures end with a `summary` the code writes: `flags`, the concerns the rules decide (a top set unchanged four or more weeks; a four-week e1RM fall of 5% or more, suppressed in a week titled Deload; sessions missed of 1.0 or more), each with its sentence; `week_line`, the whole week in one sentence with the counts; `leader_line`, who leads on what. Rule 13 says every flag appears in concerns; rule 12 says whole-week and ranking statements are copied from the two lines. Three checks: `flags_in_concerns`, `pct_grounded` (a percentage must be the quoted exercise's own, which the kilogram check could not say because loads repeat across lifts), `deload_grounded` (the word in the headline, a highlight or a concern needs a Deload title; suggestions to deload are advice and excluded). The 5% threshold is my own figure.
- **Before and after:** `story_found` 96% to 100% (48 of 48, stable in all 16 cases); `no_false_alarm` 100% held; `kg_grounded` 98% to 100%; `flags_in_concerns` 96% (rescored on the fourth run) to 100%; `deload_grounded` 98% to 100%; `pct_grounded` 90% to 100% once the check read "down 7.5%" as the figure -7.5 (a sign bug in the check, found on this run and fixed before scoring); `comparisons_grounded` 71% to 79% (38 of 48). Every original check is at 100% for the first time. Rubric means unchanged within noise (`follows_from_data` 4.42). $0.66, 48 trials, six batches, 37 minutes.
- **What remains:** the comparisons flourish, now 10 of 48: six "across the board" over five lifts in six, with the week_line saying "5 of 6" in front of the model, and four superlatives about the second-placed lift. Copying a sentence helped (14 to 10) but did not settle it. Three directions, each a measurement: Sonnet 5.5 as the reviewer on the same suite (about $1.20 batched) to learn whether the flourish is a Haiku habit; a figures block without the per-exercise percentages the model is tempted to rank; or accepting it, since the flourish is now the only error type left and the grader scores it as a wording fault, not a data one.

## Trial variation

First full run, Haiku, three trials per case: `story_found` passed in every trial for 12 of 15 cases and in some trials for the other 3 (the bench stall cases); `kg_grounded` (strict) was stable in only 6 of 15 cases, which is what pointed at the check rather than the model. Third run, 16 cases: `story_found` stable in 14 of 16, `no_false_alarm` in 15 of 16, `kg_grounded` (refined) in 15 of 16, everything else in 16 of 16; one grounding failure quoted a volume-like figure that is in neither the data nor a tool result. The grader's `follows_from_data` had the widest spread of the four dimensions (standard deviation 1.17 on Haiku's reviews, 0.74 on Sonnet's) and scored three quiet-week reviews at 2, so the grader and the code checks disagree about what a quiet week deserves; its reasons are now stored per trial for the next run to read.

## Not yet done

The `comparisons_grounded` residual, 10 of 48 after entry 12, with the three directions named there. Total project spend at the end of 2026-10-06: $11.66. Total project spend at the end of 2026-10-05: $8.93, see the slice 5 note; the follow-up note carries the spend since.
