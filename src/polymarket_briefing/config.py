from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PolymarketSettings:
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    request_timeout_seconds: float = 20
    max_retries: int = 3
    backoff_seconds: float = 1.5


@dataclass(frozen=True)
class DiscoverySettings:
    enabled: bool = True
    max_events: int = 150
    include_active_only: bool = True
    include_closed: bool = False
    min_volume_24h: float = 5000
    keywords: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoringSettings:
    min_score_to_notify: float = 35
    max_items: int = 7
    probability_change_alert_pp: float = 3.0
    score_weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class NotificationSettings:
    provider: str = "ntfy"
    dry_run_default: bool = False
    ntfy: dict[str, Any] = field(default_factory=dict)
    telegram: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StorageSettings:
    path: str = "state/briefing_state.sqlite"
    snapshot_dir: str = "state/snapshots"


@dataclass(frozen=True)
class AppConfig:
    timezone: str = "Asia/Seoul"
    run_time_local: str = "08:07"
    polymarket: PolymarketSettings = field(default_factory=PolymarketSettings)
    watchlist_slugs: list[str] = field(default_factory=list)
    discovery: DiscoverySettings = field(default_factory=DiscoverySettings)
    scoring: ScoringSettings = field(default_factory=ScoringSettings)
    notification: NotificationSettings = field(default_factory=NotificationSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return AppConfig(
        timezone=raw.get("timezone", "Asia/Seoul"),
        run_time_local=raw.get("run_time_local", "08:07"),
        polymarket=PolymarketSettings(**raw.get("polymarket", {})),
        watchlist_slugs=list(raw.get("watchlist_slugs", [])),
        discovery=DiscoverySettings(**raw.get("discovery", {})),
        scoring=ScoringSettings(**raw.get("scoring", {})),
        notification=NotificationSettings(**raw.get("notification", {})),
        storage=StorageSettings(**raw.get("storage", {})),
    )

