from __future__ import annotations

from typing import Any

from polymarket_briefing.models import NormalizedOutcome
from polymarket_briefing.utils import as_bool, as_float, as_list, parse_datetime


def normalize_event(event: dict[str, Any]) -> list[NormalizedOutcome]:
    markets = event.get("markets")
    if not isinstance(markets, list) or not markets:
        markets = [event]

    outcomes: list[NormalizedOutcome] = []
    for market in markets:
        if isinstance(market, dict):
            outcomes.extend(_normalize_market(event, market))
    return outcomes


def normalize_events(events: list[dict[str, Any]]) -> list[NormalizedOutcome]:
    normalized: list[NormalizedOutcome] = []
    for event in events:
        try:
            normalized.extend(normalize_event(event))
        except Exception:
            continue
    return normalized


def _normalize_market(event: dict[str, Any], market: dict[str, Any]) -> list[NormalizedOutcome]:
    raw_outcomes = as_list(market.get("outcomes"))
    raw_prices = as_list(market.get("outcomePrices"))
    raw_token_ids = as_list(market.get("clobTokenIds"))
    if not raw_outcomes:
        raw_outcomes = ["Yes", "No"] if market.get("question") else []

    event_slug = str(event.get("slug") or market.get("slug") or "")
    event_title = str(
        event.get("title") or event.get("question") or market.get("question") or event_slug
    )
    market_question = str(market.get("question") or event_title)
    url = f"https://polymarket.com/event/{event_slug}" if event_slug else "https://polymarket.com"

    result: list[NormalizedOutcome] = []
    for index, raw_outcome in enumerate(raw_outcomes):
        result.append(
            NormalizedOutcome(
                event_id=_string_or_none(event.get("id")),
                event_slug=event_slug,
                event_title=event_title,
                market_id=_string_or_none(market.get("id") or market.get("conditionId")),
                market_slug=_string_or_none(market.get("slug")),
                market_question=market_question,
                outcome=str(raw_outcome),
                probability=as_float(raw_prices[index] if index < len(raw_prices) else None),
                token_id=_string_or_none(
                    raw_token_ids[index] if index < len(raw_token_ids) else None
                ),
                volume=_first_float(market, "volume24hrClob", "volume", "volumeClob"),
                volume_24h=_first_float(market, "volume24hr", "volume24hrClob", "volume24h"),
                liquidity=_first_float(market, "liquidity", "liquidityClob"),
                end_date=parse_datetime(market.get("endDate") or event.get("endDate")),
                active=as_bool(market.get("active", event.get("active"))),
                closed=as_bool(market.get("closed", event.get("closed"))),
                resolution_source=_string_or_none(
                    market.get("resolutionSource") or event.get("resolutionSource")
                ),
                url=url,
                description=_string_or_none(event.get("description") or market.get("description")),
                category=_string_or_none(event.get("category") or market.get("category")),
                subcategory=_string_or_none(event.get("subcategory") or market.get("subcategory")),
            )
        )
    return result


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _first_float(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = as_float(source.get(key))
        if value is not None:
            return value
    return None
