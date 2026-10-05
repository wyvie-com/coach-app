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

## Spend

| Run | Trials | Cost |
| --- | --- | --- |
| step 2: hold and stall cases | 9 | $0.28 |
| step 3, pass 1: 16 cases, Sonnet grader | 16 | $0.49 |
| step 3, pass 2: 16 cases, Sonnet grader | 16 | $0.39 |
| step 3, pass 2 re-run of five cases | 5 | $0.12 |
| step 4: four cases through batches | 4 | $0.05 |
| **total since v0.1.0** | | **$1.33** |

Project total: $8.93 (slice 5 note) plus the table above.
