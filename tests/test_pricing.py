from datetime import datetime, timezone

from commerce_eval.core.pricing import PriceCardCatalog


def test_price_card_requires_exact_unique_match() -> None:
    catalog = PriceCardCatalog.from_mapping(
        {
            "version": "published-2026-01",
            "cards": [
                {
                    "provider": "provider-a",
                    "model": "model-a",
                    "effective_from": "2026-01-01T00:00:00Z",
                    "effective_to": "2027-01-01T00:00:00Z",
                    "currency": "USD",
                    "rates_per_million": {"prompt_tokens": 1.0, "completion_tokens": 2.0},
                }
            ],
        }
    )
    estimate = catalog.estimate(
        provider="provider-a",
        model="model-a",
        occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        usage={"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
    )
    assert estimate.amount == 2.0
    assert estimate.currency == "USD"
    assert estimate.reason == "matched"


def test_missing_or_expired_card_returns_unknown_cost() -> None:
    catalog = PriceCardCatalog("v1", [])
    estimate = catalog.estimate(
        provider="provider-a",
        model="model-a",
        occurred_at=datetime.now(timezone.utc),
        usage={"prompt_tokens": 10},
    )
    assert estimate.amount is None
    assert estimate.reason == "price_card_not_found"

