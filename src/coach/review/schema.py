"""The review's shape, twice: a JSON schema for the API and a Pydantic model for us.

Why twice: structured outputs (``output_config.format``) constrain what the model can
emit, but the supported JSON Schema subset has no ``maxItems`` beyond 0 or 1 and no
string length limits (structured outputs page, read 2026-10-05). So the API schema
says "a list of findings" and the Pydantic model says "at most three, none blank".
Both must agree on the keys; the test suite checks that.

The tool definition lives here too so the schema and the tool are reviewed together.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value.strip()


class Finding(_Strict):
    """One point in the review, tied to an exercise name from the figures or to "Overall"."""

    exercise: str
    text: str

    _check_exercise = field_validator("exercise")(_non_blank)
    _check_text = field_validator("text")(_non_blank)


class Review(_Strict):
    """The whole review. ``suggestions`` is capped here because the API schema cannot cap it."""

    headline: str
    highlights: list[Finding]
    concerns: list[Finding]
    suggestions: list[Finding] = Field(max_length=3)

    _check_headline = field_validator("headline")(_non_blank)


_FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "exercise": {
            "type": "string",
            "description": "An exercise name exactly as written in the figures, or 'Overall'.",
        },
        "text": {"type": "string", "description": "One or two plain sentences."},
    },
    "required": ["exercise", "text"],
    "additionalProperties": False,
}

REVIEW_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One sentence summing up the week.",
        },
        "highlights": {
            "type": "array",
            "description": "What went well, each tied to an exercise or 'Overall'.",
            "items": _FINDING_SCHEMA,
        },
        "concerns": {
            "type": "array",
            "description": (
                "What needs attention. Only include a concern about an exercise after "
                "calling exercise_history for it."
            ),
            "items": _FINDING_SCHEMA,
        },
        "suggestions": {
            "type": "array",
            "description": "What to change next week. At most three.",
            "items": _FINDING_SCHEMA,
        },
    },
    "required": ["headline", "highlights", "concerns", "suggestions"],
    "additionalProperties": False,
}

MAX_HISTORY_WEEKS = 12

EXERCISE_HISTORY_TOOL: dict[str, Any] = {
    "name": "exercise_history",
    "description": (
        "Returns one entry per ISO week for a single exercise over the last 1 to 12 weeks, "
        "ending at the review week, oldest first. Each entry has the week, sessions, working "
        "sets, top set weight and reps, estimated one-rep max (only when a set of ten reps or "
        "fewer exists) and mean RPE (null when none was recorded), plus the change in e1RM and "
        "RPE from the first week with data to the last, and top_set_unchanged_weeks, the number of "
        "consecutive weeks (ending at the latest week with data) in which the top set has not "
        "changed. Call it before describing any exercise "
        "as progressing, stalled or regressing, and before placing an exercise in concerns. "
        "The exercise name must match a name in the figures exactly; an unknown name returns an "
        "error listing the known names. It does not return set-by-set data, notes or other "
        "exercises."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "exercise": {
                "type": "string",
                "description": "Exercise name exactly as it appears in the figures.",
            },
            "weeks": {
                "type": "integer",
                "enum": list(range(1, MAX_HISTORY_WEEKS + 1)),
                "description": "How many ISO weeks back, ending at the review week. 1 to 12.",
            },
        },
        "required": ["exercise", "weeks"],
        "additionalProperties": False,
    },
}


class ToolInput(_Strict):
    """The tool's input, validated locally as well; strict mode should make this redundant."""

    exercise: str
    weeks: int = Field(ge=1, le=MAX_HISTORY_WEEKS)
