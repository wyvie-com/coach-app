"""The output schema the API constrains to, and the Pydantic model that validates again."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from coach.review.schema import EXERCISE_HISTORY_TOOL, REVIEW_JSON_SCHEMA, Review, ToolInput


def _walk(schema: dict) -> list[dict]:
    found = []
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            found.append(schema)
        for value in schema.values():
            found += _walk(value)
    elif isinstance(schema, list):
        for item in schema:
            found += _walk(item)
    return found


def test_every_object_in_the_review_schema_is_closed_and_fully_required() -> None:
    for obj in _walk(REVIEW_JSON_SCHEMA):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_review_schema_has_no_unsupported_array_constraint() -> None:
    text = json.dumps(REVIEW_JSON_SCHEMA)
    assert "maxItems" not in text and "minimum" not in text and "maxLength" not in text


def test_review_model_caps_suggestions_at_three() -> None:
    finding = {"exercise": "Overall", "text": "x"}
    Review.model_validate(
        {"headline": "h", "highlights": [], "concerns": [], "suggestions": [finding] * 3}
    )
    with pytest.raises(ValidationError):
        Review.model_validate(
            {"headline": "h", "highlights": [], "concerns": [], "suggestions": [finding] * 4}
        )


def test_review_model_rejects_extra_keys_and_blank_text() -> None:
    with pytest.raises(ValidationError):
        Review.model_validate(
            {"headline": "h", "highlights": [], "concerns": [], "suggestions": [], "extra": 1}
        )
    with pytest.raises(ValidationError):
        Review.model_validate(
            {"headline": "   ", "highlights": [], "concerns": [], "suggestions": []}
        )


def test_tool_definition_is_strict_with_an_enum_for_weeks() -> None:
    tool = EXERCISE_HISTORY_TOOL
    assert tool["name"] == "exercise_history"
    assert tool["strict"] is True
    schema = tool["input_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"exercise", "weeks"}
    assert schema["properties"]["weeks"]["enum"] == list(range(1, 13))
    assert len(tool["description"].split(". ")) >= 4


def test_tool_input_model_matches_the_schema() -> None:
    assert ToolInput.model_validate({"exercise": "Squat (Barbell)", "weeks": 4}).weeks == 4
    with pytest.raises(ValidationError):
        ToolInput.model_validate({"exercise": "Squat (Barbell)", "weeks": 13})
    with pytest.raises(ValidationError):
        ToolInput.model_validate({"exercise": "Squat (Barbell)"})
