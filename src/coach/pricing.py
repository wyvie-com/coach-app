"""Cost per request from the usage the API returns, priced by the model that served it.

Prices are USD per million tokens from the Claude pricing page, read on the date
below. A model missing from the table raises rather than pricing at zero, because a
silent zero is the one kind of cost figure that is worse than none.

Usage fields (prompt caching page, read 2026-10-05): ``input_tokens`` are the tokens
after the last cache breakpoint, ``cache_creation_input_tokens`` were written to the
cache, ``cache_read_input_tokens`` were read from it. When ``cache_creation`` breaks
the writes down by TTL, the one-hour share is priced at the one-hour rate.
"""

from __future__ import annotations

from dataclasses import dataclass

from anthropic.types import Usage
from pydantic import BaseModel, ConfigDict

SOURCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
READ_ON = "2026-10-05"


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float


PRICES: dict[str, Price] = {
    "claude-haiku-4-5-20251001": Price(1.00, 1.25, 2.00, 0.10, 5.00),
    "claude-sonnet-5-5": Price(2.00, 2.50, 4.00, 0.20, 10.00),
    "claude-opus-5-5": Price(4.00, 5.00, 8.00, 0.20, 20.00),
}

#: Aliases resolve to the pinned snapshot they point at (models overview, read 2026-10-05).
ALIASES: dict[str, str] = {"claude-haiku-4-5": "claude-haiku-4-5-20251001"}


class UnknownModelError(LookupError):
    """No price is known for this model id."""


class Cost(BaseModel):
    """One request's (or one run's) cost, broken down the way the pricing page prices it."""

    model_config = ConfigDict(frozen=True)

    model: str
    input_usd: float
    cache_write_usd: float
    cache_read_usd: float
    output_usd: float
    total_usd: float

    @classmethod
    def total(cls, costs: list[Cost], model: str) -> Cost:
        """Sum a list of costs."""
        fields = ("input_usd", "cache_write_usd", "cache_read_usd", "output_usd", "total_usd")
        sums = {f: sum(getattr(c, f) for c in costs) for f in fields}
        return cls(model=model, **sums)


def normalise_model(model: str) -> str:
    """Resolve an alias to its snapshot id; other names pass through unchanged."""
    return ALIASES.get(model, model)


def price_for(model: str) -> Price:
    """The price row for a model id or alias."""
    key = normalise_model(model)
    try:
        return PRICES[key]
    except KeyError:
        raise UnknownModelError(
            f"No price known for model {model!r}; add it to coach.pricing.PRICES with its source."
        ) from None


#: Message Batches: "All usage is charged at 50% of the standard API prices" (batch processing
#: page, read 2026-10-06).
BATCH_DISCOUNT = 0.5


def cost(usage: Usage, model: str, *, batch: bool = False) -> Cost:
    """Price one response's usage; ``batch`` applies the Message Batches discount."""
    key = normalise_model(model)
    price = price_for(key)
    per = 1e-6 * (BATCH_DISCOUNT if batch else 1.0)
    writes_5m = usage.cache_creation_input_tokens or 0
    writes_1h = 0
    if usage.cache_creation is not None:
        writes_5m = usage.cache_creation.ephemeral_5m_input_tokens or 0
        writes_1h = usage.cache_creation.ephemeral_1h_input_tokens or 0
    input_usd = (usage.input_tokens or 0) * price.input * per
    write_usd = writes_5m * price.cache_write_5m * per + writes_1h * price.cache_write_1h * per
    read_usd = (usage.cache_read_input_tokens or 0) * price.cache_read * per
    output_usd = (usage.output_tokens or 0) * price.output * per
    return Cost(
        model=key,
        input_usd=input_usd,
        cache_write_usd=write_usd,
        cache_read_usd=read_usd,
        output_usd=output_usd,
        total_usd=input_usd + write_usd + read_usd + output_usd,
    )
