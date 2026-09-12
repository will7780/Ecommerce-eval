"""Exact, versioned price-card matching without built-in fabricated prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional


@dataclass(frozen=True)
class CostEstimate:
    amount: Optional[float]
    currency: Optional[str]
    reason: str
    card_version: Optional[str] = None


class PriceCardCatalog:
    def __init__(self, version: str, cards: Iterable[Mapping[str, Any]]) -> None:
        if not str(version).strip():
            raise ValueError("price_card_version_required")
        self.version = str(version)
        self.cards = [dict(card) for card in cards]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PriceCardCatalog":
        cards = payload.get("cards")
        if not isinstance(cards, list):
            raise ValueError("price_cards_invalid")
        return cls(str(payload.get("version") or ""), cards)

    def estimate(
        self,
        *,
        provider: str,
        model: str,
        occurred_at: datetime,
        usage: Mapping[str, Any],
    ) -> CostEstimate:
        when = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=timezone.utc)
        matches = [card for card in self.cards if self._matches(card, provider, model, when)]
        if len(matches) != 1:
            return CostEstimate(None, None, "price_card_not_unique" if matches else "price_card_not_found")
        card = matches[0]
        rates = card.get("rates_per_million")
        if not isinstance(rates, Mapping):
            return CostEstimate(None, None, "price_card_rates_invalid")
        total = 0.0
        billed = False
        for usage_key, rate_key in (
            ("prompt_tokens", "prompt_tokens"),
            ("completion_tokens", "completion_tokens"),
            ("reasoning_tokens", "reasoning_tokens"),
            ("cache_hit_tokens", "cache_hit_tokens"),
            ("cache_miss_tokens", "cache_miss_tokens"),
        ):
            tokens = usage.get(usage_key)
            rate = rates.get(rate_key)
            if tokens is None:
                continue
            if rate is None:
                return CostEstimate(None, None, f"price_card_rate_missing:{rate_key}")
            try:
                total += float(tokens) * float(rate) / 1_000_000.0
            except (TypeError, ValueError):
                return CostEstimate(None, None, f"price_card_rate_invalid:{rate_key}")
            billed = True
        if not billed:
            return CostEstimate(None, None, "usage_unavailable")
        return CostEstimate(total, str(card.get("currency") or ""), "matched", self.version)

    @staticmethod
    def _matches(card: Mapping[str, Any], provider: str, model: str, when: datetime) -> bool:
        if str(card.get("provider")) != provider or str(card.get("model")) != model:
            return False
        try:
            start = datetime.fromisoformat(str(card["effective_from"]).replace("Z", "+00:00"))
            end_raw = card.get("effective_to")
            end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00")) if end_raw else None
        except (KeyError, TypeError, ValueError):
            return False
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return start <= when and (end is None or when < end)

