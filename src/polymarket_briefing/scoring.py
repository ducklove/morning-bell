from __future__ import annotations

import math
from datetime import datetime, timedelta

from polymarket_briefing.config import AppConfig
from polymarket_briefing.models import NormalizedOutcome, ScoredOutcome

DEFAULT_WEIGHTS = {
    "change_signal": 0.40,
    "relevance_signal": 0.25,
    "volume_signal": 0.15,
    "probability_signal": 0.10,
    "deadline_signal": 0.07,
    "liquidity_signal": 0.03,
}


def score_outcomes(
    outcomes: list[NormalizedOutcome],
    deltas: dict[tuple[str, str | None, str], float | None],
    config: AppConfig,
    observed_at: datetime,
) -> list[ScoredOutcome]:
    max_volume = max((item.volume_24h or item.volume or 0 for item in outcomes), default=0)
    max_liquidity = max((item.liquidity or 0 for item in outcomes), default=0)
    scored = [
        score_outcome(item, deltas.get(_key(item)), config, observed_at, max_volume, max_liquidity)
        for item in outcomes
    ]
    return sorted(scored, key=lambda item: item.score, reverse=True)


def score_outcome(
    outcome: NormalizedOutcome,
    delta_24h_pp: float | None,
    config: AppConfig,
    observed_at: datetime,
    max_volume_seen: float,
    max_liquidity_seen: float,
) -> ScoredOutcome:
    weights = DEFAULT_WEIGHTS | config.scoring.score_weights
    signals = {
        "change_signal": change_signal(delta_24h_pp),
        "relevance_signal": relevance_signal(outcome, config),
        "volume_signal": log_signal(outcome.volume_24h or outcome.volume, max_volume_seen),
        "probability_signal": probability_signal(outcome.probability),
        "deadline_signal": deadline_signal(outcome, observed_at),
        "liquidity_signal": log_signal(outcome.liquidity, max_liquidity_seen),
    }
    score = sum(weights[name] * 100 * signals[name] for name in weights)
    return ScoredOutcome(
        outcome=outcome,
        score=max(0, min(score, 100)),
        delta_24h_pp=delta_24h_pp,
        reasons=tuple(reasons_for(outcome, signals, delta_24h_pp, config)),
    )


def change_signal(delta_24h_pp: float | None) -> float:
    if delta_24h_pp is None:
        return 0
    return min(abs(delta_24h_pp) / 10.0, 1.0)


def relevance_signal(outcome: NormalizedOutcome, config: AppConfig) -> float:
    score = 0.8 if outcome.event_slug in config.watchlist_slugs else 0.0
    haystack = " ".join(
        filter(
            None,
            [
                outcome.event_title,
                outcome.market_question,
                outcome.description,
                outcome.category,
                outcome.subcategory,
            ],
        )
    ).lower()
    for profile in config.discovery.keywords.values():
        weight = float(profile.get("weight", 1.0))
        for term in profile.get("terms", []):
            if str(term).lower() in haystack:
                score = max(score, min(weight, 1.0))
    return min(score, 1.0)


def log_signal(value: float | None, max_seen: float) -> float:
    if value is None or value <= 0 or max_seen <= 0:
        return 0
    return min(math.log1p(value) / math.log1p(max_seen), 1.0)


def probability_signal(probability: float | None) -> float:
    if probability is None:
        return 0.3
    bounded = max(0.0, min(probability, 1.0))
    return max(0.0, 1.0 - abs(bounded - 0.5) * 2)


def deadline_signal(outcome: NormalizedOutcome, observed_at: datetime) -> float:
    if outcome.end_date is None:
        return 0
    remaining = outcome.end_date - observed_at
    if remaining <= timedelta(days=7):
        return 1.0
    if remaining <= timedelta(days=30):
        return 0.6
    if remaining <= timedelta(days=90):
        return 0.3
    return 0.1


def reasons_for(
    outcome: NormalizedOutcome,
    signals: dict[str, float],
    delta_24h_pp: float | None,
    config: AppConfig,
) -> list[str]:
    reasons: list[str] = []
    if outcome.event_slug in config.watchlist_slugs:
        reasons.append("watchlist")
    if delta_24h_pp is not None and abs(delta_24h_pp) >= config.scoring.probability_change_alert_pp:
        reasons.append("24h 급변")
    if signals["relevance_signal"] >= 0.8:
        reasons.append("관심 키워드")
    if signals["volume_signal"] >= 0.8:
        reasons.append("거래량 큼")
    if signals["deadline_signal"] >= 0.6:
        reasons.append("정산 임박")
    return reasons or ["관심도 점수"]


def _key(outcome: NormalizedOutcome) -> tuple[str, str | None, str]:
    return (outcome.event_slug, outcome.market_id, outcome.outcome)
