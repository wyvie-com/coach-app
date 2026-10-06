# Follow-up: the six-step plan after v0.1.0

Date: 2026-10-06. Branch `claude/funny-cori-evrx1v`. Continues from the slice 5 note.

The plan agreed with the owner, in order: a docs line on saving run outputs; the two-week hold; the two review weaknesses the Sonnet grader surfaced; Message Batches (the optional slice 6); a full run on the final prompt; a fresh review of the current real week.

## Step 1: run outputs are ephemeral

`docs/live-runs.md` now says that `private/` and `out/` live only in the session container and should be archived after each live run. Found when the owner asked whether the data was being saved; the answer was no.

## Step 2: the two-week hold

`docs/findings.md` entry 9. The count of unchanged weeks moved from the tool result alone into the week's figures as well, computed by one helper for both. Rule 2 tightened. Hold case 0 of 3, then 4 of 6, now 3 of 3; bench stall held at 6 of 6.

Decision: fix the figures, not the prompt alone. The failing reviews showed the model deciding "stalled" from the history's shape before it had the count in front of it. Putting the count in the figures is the project's thesis applied once more: code computes, the model reads.

## Step 3: the weaknesses the stronger grader found

`docs/findings.md` entry 10. Two passes. The first added prior-week volume and a prompt rule; it changed nothing the grader could see. The second moved the comparison into code (`leaders`, `counts`), added the `comparisons_grounded` check, and halved the number of tool calls as a side effect. Wrong superlatives fell from 5 of 16 to 1 of 16.

Decisions:

- **Measure with a code check, not the rubric.** At one trial per case the rubric cannot resolve a change under half a point. The check can count the exact error the grader described, costs nothing, and runs on real weeks too.
- **Exempt the leader from the universal-claim check.** "Led all exercises with 14.3%" by the exercise that leads is a ranking, which the leaders figure backs; the first version of the check failed it.
- **Stop at two passes.** The remaining grader criticisms are percentages moved between fields of the same exercise. Fixing that means fewer fields in the figures, which is a design change for `docs/later.md`, not a third pass on this plan.

## Step 4: Message Batches

`docs/notes/slice-6.md`. The loop became a resumable session so the batch path and the live path share one body; the suite runs as rounds of batches at half price. Verified live on four cases: 4 of 4 ok, $0.05, 16 minutes.

## Step 5: the full run on the final prompt

`docs/findings.md` entry 11. 16 cases, 3 trials, batched: story found 96%, no false alarm 100%, every other original check 98 to 100%, the new comparisons check 71%. $0.64 and 34 minutes, six batches, every request succeeded.

Decision: stop here rather than chase the comparisons residual with more prompt. Two candidates are recorded for later, a shorter figures block and a Sonnet-reviewed run of the suite, each a measurement with a price.

## Step 6: the last complete real week again, on the final prompt

Week 2026-W40 reviewed a second time on Haiku, after a fresh pull (612 workouts). Aggregates only: outcome ok, 7 turns, 6 tool calls (every exercise it put in concerns plus the two it praised), all 7 data checks passed including the new `comparisons_grounded`, $0.032 against $0.026 on 2026-10-05. It raised four concerns where the first review raised two and Opus three; every one of the four is a stall of four or more unchanged weeks or a four-week e1RM fall, which is what rule 2 now asks for. Real weeks have more exercises than the synthetic ones (twelve against six), so the model looks up more and the review costs more; the synthetic suite's one tool call per review does not transfer.

## Spend

| Run | Trials | Cost |
| --- | --- | --- |
| step 2: hold and stall cases | 9 | $0.28 |
| step 3, pass 1: 16 cases, Sonnet grader | 16 | $0.49 |
| step 3, pass 2: 16 cases, Sonnet grader | 16 | $0.39 |
| step 3, pass 2 re-run of five cases | 5 | $0.12 |
| step 4: four cases through batches | 4 | $0.05 |
| step 5: full run, 16 cases x 3 trials, batched | 48 | $0.64 |
| step 6: real week 2026-W40 on the final prompt | 1 | $0.03 |
| **total since v0.1.0** | | **$2.00** |

Project total: $8.93 (slice 5 note) plus $2.00 above, $10.93. The plan's estimate was $2.87 before buffer; the batched full run and the cheaper Sonnet-graded passes brought it in under.
