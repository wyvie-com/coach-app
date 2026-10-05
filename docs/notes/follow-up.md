# Follow-up: the six-step plan after v0.1.0

Date: 2026-10-06. Branch `claude/funny-cori-evrx1v`. Continues from the slice 5 note.

The plan agreed with the owner, in order: a docs line on saving run outputs; the two-week hold; the two review weaknesses the Sonnet grader surfaced; Message Batches (the optional slice 6); a full run on the final prompt; a fresh review of the current real week.

## Step 1: run outputs are ephemeral

`docs/live-runs.md` now says that `private/` and `out/` live only in the session container and should be archived after each live run. Found when the owner asked whether the data was being saved; the answer was no.

## Step 2: the two-week hold

`docs/findings.md` entry 9. The count of unchanged weeks moved from the tool result alone into the week's figures as well, computed by one helper for both. Rule 2 tightened. Hold case 0 of 3, then 4 of 6, now 3 of 3; bench stall held at 6 of 6.

Decision: fix the figures, not the prompt alone. The failing reviews showed the model deciding "stalled" from the history's shape before it had the count in front of it. Putting the count in the figures is the project's thesis applied once more: code computes, the model reads.

## Spend

| Run | Trials | Cost |
| --- | --- | --- |
| step 2: hold and stall cases | 9 | $0.28 |
| **total since v0.1.0** | | **$0.28** |

Project total: $8.93 (slice 5 note) plus the table above.
