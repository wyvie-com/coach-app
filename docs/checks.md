# What the code checks measure

Current definitions, 2026-10-07. Thirteen code checks run on every eval trial. The eleven marked "real weeks" also run on every review of a real week (`coach review`). A pass means the check found nothing wrong within what it reads; it is not an accuracy rate, and a review can be valid for the API and the schema and still fail any of these.

A check with nothing to test reports **n/a**, not a pass, and pass rates leave it out: `expected_placement` on a negative case, where nothing was planted, and both flag checks in a week with no flags. The eval report gives negative cases their own row: `no_false_alarm` on those cases alone.

| Check | Real weeks | Measures | Does not measure |
| --- | --- | --- | --- |
| `schema_valid` | yes | The run ended with a review that validated against the schema. | Whether anything in it is true. |
| `expected_placement` | no | The planted story's exercise, or "Overall", appears in the expected section. n/a on a negative case. Called `story_found` until 2026-10-07. | What the finding says: the right exercise in the right section with the wrong words passes. |
| `no_false_alarm` | no | No concern names an exercise, or "Overall", on which nothing was planted. | False alarms in highlights or suggestions, or a planted exercise raised for the wrong reason. |
| `exercises_exist` | yes | Every exercise a finding names is in the week's figures. | Whether a real name is attached to the right claim. |
| `kg_grounded` | yes | Every kilogram number in the headline, highlights and concerns is within 0.5 kg of a computed value or a tool result, or of the difference between two values for the same exercise. | Which exercise, metric or week the number belongs to; suggestions. Passes when nothing is quoted. |
| `concern_preceded_by_tool` | yes | Every exercise in concerns had a successful history lookup in the run. | Whether the lookup supports the conclusion; progress or regression claimed outside concerns. |
| `max_three_suggestions` | yes | At most three suggestions. Redundant while the schema caps them. | Whether the suggestions are any good. |
| `sessions_threshold` | yes | No "Overall" concern mentions sessions when fewer than one session was missed. | Claims about sessions anywhere else. |
| `comparisons_grounded` | yes | A superlative names a lift that holds the claimed place on some figure: alone at the top for "the largest", that place for "the second-largest", the top half for "one of the largest", counted from the bottom for a fall ("the largest decline"); a lift's own best ("the strongest yet") is not a ranking. "All", "every" or "across the board" must match the counts: every lift up for progress, every lift down for a reduction, most for "nearly all", the stated number for "all five"; said of effort or RPE, it is not read. | Which figure the ranking refers to: a lift that leads on volume can be called the strongest. A leading lift's sentence generalising to every lift; advice about the future and claims about a group of lifts ("the upper-body lifts"), which are read as claims about every lift. |
| `flags_carried` | yes | For every flag the code raised, a concern under its exercise, or "Overall", states the flagged condition and says nothing opposite to it, read as described below. n/a in a week with no flags. Replaced `flags_in_concerns` on 2026-10-07. | The numbers in the statement (how many weeks, how large a fall, how many sessions); phrasing outside the word families. |
| `flags_consistent` | yes | No highlight or concern under a flagged exercise says the opposite of its flag: progress for a stall, a rise for a fall, full attendance for missed sessions, or the condition negated. n/a in a week with no flags. | The headline and suggestions; an opposite phrased outside the word families. |
| `pct_grounded` | yes | Every percentage in a finding about one exercise is one of that exercise's percentage figures, in the figures or a tool result; the headline and "Overall" findings may quote any exercise's. | The sign (a fall written as a rise passes), the metric or the window; suggestions; the top of a range ("4-9%"), which is a summary, not a figure. |
| `deload_grounded` | yes | The headline, highlights and concerns call the week a deload only when a session title says "Deload". | Suggestions to deload, which are advice and deliberately not read, and the same advice inside a concern ("a brief deload may help"). |

The rubric grader is a separate model call that scores four dimensions from 1 to 5: follows from the data, specific, safe, concise. It has not been calibrated against human labels, so its scores are signals, not measurements, and it is the only judge of meaning beyond the checks above.

## How the flag checks read prose

`coach.evals.flag_text` reads one finding against one flag by word families and nothing cleverer:

- **A stall:** unchanged, stalled, stuck, flat, plateaued, held at, the same top set, the same as five weeks ago, no progress, hasn't increased, hasn't gone up, or a stated duration ("for five weeks", "for the last five weeks", "every week") when nothing in the finding rose or fell.
- **A fall:** down, fell, dropped, declined, regressed, slid, lower, gone backwards.
- **Missed sessions:** missed, skipped, fewer, only one session, one of three, trained once, below the baseline.
- **Opposites:** progressing, improved, rose, climbing, up 7.5%, a new PR for a stall or a fall; all sessions done, on track, nothing missed for missed sessions; and the condition itself negated ("not stalled", "hasn't dropped").

It reads negation from the three words before a cue ("not progressing", "hasn't increased"), from a "no" or "without" in front of a short "or" list ("no load or rep increase"), from a stall word just before the noun "progress" ("stalled progress", "a stall in progress"), from a stopping word anywhere before it ("halting the steady weekly advances"), and from a stopping word just after it ("progress has stalled"). Advice is not a claim: "time to push for an increase", consistent attendance "is essential". It ignores wishes ("needs to progress"), earlier weeks ("after steady progress earlier", "rose until week 36"), cues about effort or volume ("the rising RPE"), and, for an exercise's flag, clauses that name another lift or "other lifts". The flagged lift's own name is read as "it", so its words neither name another lift ("incline" in Seated Incline Curl, beside Incline Bench Press) nor make a claim ("decline" in Decline Bench Press); a longer name that contains it, such as Straight Arm Lat Pulldown for Lat Pulldown, still names another lift. A finding that both states the condition and says the opposite does not carry the flag.

`tests/test_eval_flag_checks.py` pins each rule with findings built to pass and to fail: correct paraphrases, a missing finding, a contradiction, an irrelevant finding, the wrong reason, the wrong direction, two flags on one exercise, negative cases, lift names that contain another lift's name, the correct sentences it misread on Claude's stored reviews (findings entries 15 and 16), and three limits a later change should close on purpose.

**Why this design.** It changes nothing the reviewer model sees, so live behaviour is as before, and it can be tested offline. The alternatives were a flag identifier in the review schema, or flag sentences rendered into the review by code. Both change what the model is asked to produce, which no offline test can validate, and an identifier alone would still leave the prose beside it free to contradict it. Either may follow once the narrow reader has been measured on model output.

## The counterexample that prompted this

A review built by hand for the planted bench stall (`bench_stall-1`, flag: top set unchanged at 80 kg x 5 for five weeks): the bench in concerns with the text "Bench is progressing normally and is not stalled.", and a successful history lookup recorded. It is not model output, and the rubric grader was not run on it.

| | Before 2026-10-07 | After |
| --- | --- | --- |
| Checks passed | all 12 | 11 of 13 |
| Placement | `story_found` passed | `expected_placement` passes: the bench is in concerns |
| Flag | `flags_in_concerns` passed | `flags_carried` fails: no concern states the stall |
| Prose | not read | `flags_consistent` fails: the concern says "progressing" |

It is the first test in `tests/test_eval_flag_checks.py`.

## Known limits

- **The flag checks read words, not meaning.** They do not read the headline or suggestions, check numbers inside the statement, or follow phrasing outside their word families. On Claude's 164 stored eval reviews they wrongly failed 8 of the 89 trials that had a flag, in three patterns (findings entry 15); 0.3.2 fixes all three, but those fixes were tuned on the same trials (entry 16), and their rate on reviews they were not tuned on is not yet measured. On four real-week reviews they wrongly failed one correct concern, a bug fixed in 0.3.1 (entry 14). A shortened name for the flagged lift that contains another lift's short name ("the incline curl", beside Incline Bench Press) is still read as being about the other lift.
- **Kilogram grounding is a pool, not an attribution.** A real figure attached to the wrong exercise, metric or week passes. Percentage grounding ties a figure to its exercise but ignores the sign and the window. Neither reads suggestions, which may propose new loads.
- **Stories beyond the flags are checked for placement only.** A rep PR, rising effort at the same load and steady progress have no code check on what the finding says.
- **History lookups are counted, not judged.** `concern_preceded_by_tool` covers exercises in concerns only, and a lookup does not make the conclusion right.
- **Rankings are checked against any figure.** `comparisons_grounded` accepts a superlative for a lift that leads on some figure, not necessarily the one the sentence names.
- **The CLI does not gate on quality.** `coach review` prints the checks beside the review and exits successfully even when a check fails.
- **The rubric grader is uncalibrated.** Free-text meaning beyond these checks rests on it.
