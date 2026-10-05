# Hevy fixtures

Synthetic pages produced by `make_fixtures.py`; nothing here comes from a real account. Ids are counters padded into UUID shape, exercise template ids are `TPL0000n`, timestamps start at a fixed instant. Regenerate with `uv run python tests/fixtures/hevy/make_fixtures.py`.

Shapes follow the Hevy OpenAPI document (version 0.0.1) embedded in `https://api.hevyapp.com/docs/swagger-ui-init.js`, read on **2026-10-05**:

- `GET /v1/workouts` → `{page, page_count, workouts[]}`; `pageSize` max 10.
- `GET /v1/workouts/count` → `{workout_count}`.
- Workout → `id, title, routine_id, description, start_time, end_time, updated_at, created_at, exercises[]`.
- Exercise → `index, title, notes, exercise_template_id, superset_id (nullable), sets[]`.
- Set → `index, type, weight_kg, reps, distance_meters, duration_seconds, rpe, custom_metric` (all numeric fields nullable); `type` one of `normal, warmup, dropset, failure`.

The fixture pages hold two workouts each so the files stay small; the client never checks a page's length against `pageSize`, only `page` and `page_count`. Two deliberately malformed pages exist for the rejection tests.
