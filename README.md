# Coach

**Status: in development.**

Coach is a personal AI training coach built on a Hevy training log. It pulls workouts through the Hevy API, computes the week's figures in code (volume, top sets, estimated one-rep maxes, trends, missed sessions), and asks Claude to write a short weekly review that only interprets those figures: what went well, what needs attention, what to change next week. The model can check a lift's history through one strict tool before calling it progressing, stalled or regressing, and its answer is constrained to a JSON schema and validated again locally.

The review is measured, not admired. An evaluation suite runs synthetic training logs with planted stories (a bench stall, a squat PR, rising RPE at the same load, missed sessions, a regression, and two weeks where nothing is wrong) through the same code path, checks the output with code first and a model-graded rubric second, and reports pass rates, rubric spread, cost and latency per model side by side. Real account data and every run output stay under gitignored directories; the repository holds code, synthetic fixtures and aggregate findings only. The design is in `docs/spec.md`; each build slice has a note under `docs/notes/`.
