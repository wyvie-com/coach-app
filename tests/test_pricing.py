"""Cost comes from the usage the API returns, priced by the model that served the request."""

from __future__ import annotations

import pytest
from anthropic.types import Usage

from coach import pricing


def test_haiku_cost_with_cache_reads_and_writes() -> None:
    usage = Usage(
        input_tokens=1000,
        output_tokens=2000,
        cache_creation_input_tokens=4000,
        cache_read_input_tokens=8000,
    )
    cost = pricing.cost(usage, "claude-haiku-4-5-20251001")
    # $1 input, $1.25 5m write, $0.10 read, $5 output per million tokens (pricing page, 2026-10-05).
    assert cost.input_usd == pytest.approx(0.001)
    assert cost.cache_write_usd == pytest.approx(0.005)
    assert cost.cache_read_usd == pytest.approx(0.0008)
    assert cost.output_usd == pytest.approx(0.010)
    assert cost.total_usd == pytest.approx(0.0168)
    assert cost.model == "claude-haiku-4-5-20251001"


def test_missing_cache_fields_count_as_zero() -> None:
    cost = pricing.cost(Usage(input_tokens=100, output_tokens=0), "claude-haiku-4-5-20251001")
    assert cost.total_usd == pytest.approx(0.0001)


def test_one_hour_cache_writes_use_the_one_hour_price() -> None:
    usage = Usage(
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1000,
        cache_creation={"ephemeral_5m_input_tokens": 400, "ephemeral_1h_input_tokens": 600},
    )
    cost = pricing.cost(usage, "claude-haiku-4-5-20251001")
    assert cost.cache_write_usd == pytest.approx(400 * 1.25e-6 + 600 * 2.0e-6)


def test_alias_is_priced_as_its_snapshot() -> None:
    assert pricing.normalise_model("claude-haiku-4-5") == "claude-haiku-4-5-20251001"
    assert pricing.cost(Usage(input_tokens=1, output_tokens=0), "claude-haiku-4-5").model == (
        "claude-haiku-4-5-20251001"
    )


def test_unknown_model_raises_not_zero() -> None:
    with pytest.raises(pricing.UnknownModelError, match="claude-made-up"):
        pricing.cost(Usage(input_tokens=1, output_tokens=1), "claude-made-up")


def test_table_carries_its_source_and_date() -> None:
    assert pricing.SOURCE_URL.startswith("https://platform.claude.com/docs/")
    assert pricing.READ_ON == "2026-10-05"
    for model in ("claude-sonnet-5-5", "claude-opus-5-5"):
        assert model in pricing.PRICES
