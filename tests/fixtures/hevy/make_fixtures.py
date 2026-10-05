"""Generate the synthetic Hevy fixture pages.

Run with ``uv run python tests/fixtures/hevy/make_fixtures.py``.
Why a generator and not hand-written JSON: it proves the fixtures are synthetic.
Every id is built from a counter, every timestamp from a fixed start, and no value
comes from a real account. The shapes follow the Hevy OpenAPI document read on
2026-10-05 (see README.md beside this file).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
START = datetime(2026, 9, 14, 21, 30, tzinfo=UTC)  # 07:30 Melbourne (AEST), a Tuesday morning
LIFTS = [
    ("Squat (Barbell)", "TPL00001"),
    ("Bench Press (Barbell)", "TPL00002"),
    ("Deadlift (Barbell)", "TPL00003"),
    ("Overhead Press (Barbell)", "TPL00004"),
]


def _set(index: int, kind: str, weight: float | None, reps: int | None, rpe: float | None) -> dict:
    return {
        "index": index,
        "type": kind,
        "weight_kg": weight,
        "reps": reps,
        "distance_meters": None,
        "duration_seconds": None,
        "rpe": rpe,
        "custom_metric": None,
    }


def _exercise(index: int, title: str, template_id: str, top_kg: float) -> dict:
    return {
        "index": index,
        "title": title,
        "notes": "",
        "exercise_template_id": template_id,
        "superset_id": None,
        "sets": [
            _set(0, "warmup", round(top_kg * 0.5, 1), 8, None),
            _set(1, "warmup", round(top_kg * 0.75, 1), 5, None),
            _set(2, "normal", top_kg, 5, 8.0),
            _set(3, "normal", top_kg, 5, 8.5),
            _set(4, "normal", top_kg, 5, 9.0),
        ],
    }


def _workout(n: int) -> dict:
    start = START + timedelta(days=2 * n)
    stamp = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (start + timedelta(minutes=65)).strftime("%Y-%m-%dT%H:%M:%SZ")
    title, template_id = LIFTS[n % len(LIFTS)]
    second, second_id = LIFTS[(n + 1) % len(LIFTS)]
    return {
        "id": f"00000000-0000-4000-8000-{n:012d}",
        "title": f"Session {n + 1}",
        "routine_id": None,
        "description": "",
        "start_time": stamp,
        "end_time": end,
        "updated_at": end,
        "created_at": end,
        "exercises": [
            _exercise(0, title, template_id, 60.0 + 2.5 * n),
            _exercise(1, second, second_id, 40.0 + 2.5 * n),
        ],
    }


def main() -> None:
    """Write three pages of two workouts each, a count, and two malformed pages."""
    per_page = 2
    pages = 3
    workouts = [_workout(n) for n in range(per_page * pages)]
    for page in range(1, pages + 1):
        chunk = workouts[(page - 1) * per_page : page * per_page]
        body = {"page": page, "page_count": pages, "workouts": chunk}
        (HERE / f"workouts-page-{page}.json").write_text(json.dumps(body, indent=2) + "\n")
    (HERE / "workouts-count.json").write_text(
        json.dumps({"workout_count": len(workouts)}, indent=2) + "\n"
    )
    # Malformed: the key the client depends on is missing.
    (HERE / "malformed-missing-workouts.json").write_text(
        json.dumps({"page": 1, "page_count": 1}, indent=2) + "\n"
    )
    # Malformed: a start_time without a UTC offset, which the client must refuse to guess.
    naive = _workout(0)
    naive["start_time"] = "2026-09-15T07:30:00"
    (HERE / "malformed-naive-start-time.json").write_text(
        json.dumps({"page": 1, "page_count": 1, "workouts": [naive]}, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
