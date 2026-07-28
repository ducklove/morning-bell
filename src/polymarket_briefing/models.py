from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ReasonCode(StrEnum):
    """Why an outcome was surfaced.

    Selection logic branches on these, so they are stable identifiers rather
    than the Korean strings shown to the reader — editing a display label used
    to silently change which items got selected.
    """

    RECENTLY_SENT = "recently_sent"
    EVENT_RECENTLY_SENT = "event_recently_sent"
    WATCHLIST = "watchlist"
    SHARP_CHANGE = "sharp_change"
    KEYWORD = "keyword"
    HIGH_VOLUME = "high_volume"
    DEADLINE = "deadline"
    BASELINE = "baseline"


@dataclass(frozen=True)
class NormalizedOutcome:
    event_id: str | None
    event_slug: str
    event_title: str
    market_id: str | None
    market_slug: str | None
    market_question: str
    outcome: str
    probability: float | None
    token_id: str | None
    volume: float | None
    volume_24h: float | None
    liquidity: float | None
    end_date: datetime | None
    active: bool | None
    closed: bool | None
    resolution_source: str | None
    url: str
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None


@dataclass(frozen=True)
class ScoredOutcome:
    outcome: NormalizedOutcome
    score: float
    delta_24h_pp: float | None = None
    reasons: tuple[ReasonCode, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Snapshot:
    observed_at: datetime
    event_slug: str
    market_id: str | None
    market_question: str
    outcome: str
    probability: float | None
    volume: float | None
    volume_24h: float | None
    liquidity: float | None
    url: str


def outcome_key(outcome: NormalizedOutcome) -> tuple[str, str | None, str]:
    return (outcome.event_slug, outcome.market_id, outcome.outcome)


def outcome_haystack(outcome: NormalizedOutcome) -> str:
    return " ".join(
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

