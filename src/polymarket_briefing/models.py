from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
    reasons: tuple[str, ...] = field(default_factory=tuple)


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
