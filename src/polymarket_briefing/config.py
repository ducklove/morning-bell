from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

import yaml


@dataclass(frozen=True)
class PolymarketSettings:
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    request_timeout_seconds: float = 20
    max_retries: int = 3
    backoff_seconds: float = 1.5
    # Gamma API caps a single /events request at 100 items; discovery pages
    # through repeated requests until it reaches discovery.max_events.
    page_size: int = 100


@dataclass(frozen=True)
class DiscoverySettings:
    enabled: bool = True
    max_events: int = 150
    include_active_only: bool = True
    include_closed: bool = False
    min_volume_24h: float = 5000
    exclude_terms: list[str] = field(default_factory=list)
    keywords: dict[str, dict[str, Any]] = field(default_factory=dict)


DEFAULT_SCORE_WEIGHTS = {
    "change_signal": 0.40,
    "relevance_signal": 0.25,
    "volume_signal": 0.15,
    "probability_signal": 0.10,
    "deadline_signal": 0.07,
    "liquidity_signal": 0.03,
}


@dataclass(frozen=True)
class ScoringSettings:
    min_score_to_notify: float = 35
    max_items: int = 7
    probability_change_alert_pp: float = 3.0
    sent_penalty_days: int = 7
    sent_penalty_factor: float = 0.25
    sent_event_penalty_factor: float = 0.60
    # Outcomes below this probability are hopeless long shots (e.g. a 0.1%
    # candidate) and are hidden from the briefing body.
    min_probability_to_show: float = 0.03
    # Collapse near-duplicate events on the same topic (e.g. "Largest Company
    # end of July" vs. "... end of August") down to this many per topic.
    max_events_per_topic: int = 1
    score_weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AiSummarySettings:
    enabled: bool = False
    model: str = "qwen/qwen3.6-flash"
    max_retries: int = 3
    timeout_seconds: float = 45
    backoff_seconds: float = 1.5


@dataclass(frozen=True)
class NotificationSettings:
    provider: str = "ntfy"
    dry_run_default: bool = False
    ntfy: dict[str, Any] = field(default_factory=dict)
    telegram: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StorageSettings:
    path: str = "state/briefing_state.sqlite"
    retention_days: int = 30


@dataclass(frozen=True)
class AppConfig:
    timezone: str = "Asia/Seoul"
    polymarket: PolymarketSettings = field(default_factory=PolymarketSettings)
    watchlist_slugs: list[str] = field(default_factory=list)
    discovery: DiscoverySettings = field(default_factory=DiscoverySettings)
    scoring: ScoringSettings = field(default_factory=ScoringSettings)
    ai_summary: AiSummarySettings = field(default_factory=AiSummarySettings)
    notification: NotificationSettings = field(default_factory=NotificationSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)


SettingsT = TypeVar("SettingsT")


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    _reject_unknown_keys(raw, _valid_keys(AppConfig), "top-level config")
    scoring_raw = dict(raw.get("scoring") or {})
    _validate_score_weights(scoring_raw.get("score_weights") or {})
    return AppConfig(
        timezone=raw.get("timezone", "Asia/Seoul"),
        polymarket=_build(PolymarketSettings, raw.get("polymarket"), "polymarket"),
        watchlist_slugs=list(raw.get("watchlist_slugs") or []),
        discovery=_build(DiscoverySettings, raw.get("discovery"), "discovery"),
        scoring=_build(ScoringSettings, scoring_raw, "scoring"),
        ai_summary=_build(AiSummarySettings, raw.get("ai_summary"), "ai_summary"),
        notification=_build(NotificationSettings, raw.get("notification"), "notification"),
        storage=_build(StorageSettings, raw.get("storage"), "storage"),
    )


def _valid_keys(settings_cls: type) -> list[str]:
    """Valid config keys for a settings dataclass, derived from its fields."""
    return [f.name for f in fields(settings_cls)]


def _build(settings_cls: type[SettingsT], section_raw: Any, section: str) -> SettingsT:
    """Build a settings dataclass from raw YAML, rejecting unknown keys."""
    values = dict(section_raw or {})
    _reject_unknown_keys(values, _valid_keys(settings_cls), section)
    return settings_cls(**values)


def _reject_unknown_keys(values: Any, valid_keys: list[str], section: str) -> None:
    unknown = set(values or {}) - set(valid_keys)
    if unknown:
        raise ValueError(
            f"Unknown {section} keys: {sorted(unknown)}. Valid keys: {sorted(valid_keys)}"
        )


def _validate_score_weights(score_weights: dict[str, float]) -> None:
    _reject_unknown_keys(score_weights, list(DEFAULT_SCORE_WEIGHTS), "scoring.score_weights")
