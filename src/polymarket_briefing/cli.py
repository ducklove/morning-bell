from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from polymarket_briefing.ai_summary import load_openrouter_key, summarize_with_openrouter
from polymarket_briefing.charts import build_price_charts
from polymarket_briefing.config import load_config
from polymarket_briefing.models import NormalizedOutcome
from polymarket_briefing.normalize import normalize_event, normalize_events
from polymarket_briefing.notifier import notify
from polymarket_briefing.polymarket_client import PolymarketClient
from polymarket_briefing.scoring import score_outcomes
from polymarket_briefing.storage import (
    BriefingStorage,
    calculate_snapshot_delta_pp,
    dedupe_key_for,
)
from polymarket_briefing.summarize import summarize
from polymarket_briefing.utils import utc_now

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml"),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    ai_summary: Annotated[bool, typer.Option("--ai-summary")] = False,
    ai_model: Annotated[str, typer.Option("--ai-model")] = "qwen/qwen3.6-flash",
) -> None:
    cfg = load_config(config)
    observed_at = utc_now()
    with PolymarketClient(cfg.polymarket) as client, BriefingStorage(cfg.storage.path) as storage:
        outcomes = _fetch_all(client, cfg)
        deltas = _calculate_deltas(client, storage, outcomes, observed_at, set(cfg.watchlist_slugs))
        scored = score_outcomes(outcomes, deltas, cfg, observed_at)
        selected = _select_items(scored, set(cfg.watchlist_slugs), cfg.scoring.min_score_to_notify)
        selected = selected[: cfg.scoring.max_items]
        message = summarize(selected, cfg.scoring.max_items, cfg.timezone)
        if ai_summary:
            api_key = load_openrouter_key()
            if not api_key:
                raise RuntimeError("OPENROUTER_API_KEY or keys openrouter entry is required")
            message = summarize_with_openrouter(selected, message, api_key, model=ai_model)
        effective_dry_run = dry_run or cfg.notification.dry_run_default
        attachments = []
        if cfg.notification.provider.lower() == "telegram":
            attachments = build_price_charts(client, selected, observed_at)
        if selected:
            top = selected[0]
            key = dedupe_key_for(
                observed_at,
                top.outcome.event_slug,
                top.outcome.market_id,
                top.outcome.outcome,
                top.outcome.probability,
                top.delta_24h_pp,
            )
            if effective_dry_run or not storage.notification_sent(key):
                notify(
                    cfg.notification,
                    message,
                    dry_run=effective_dry_run,
                    attachments=attachments,
                )
                if not effective_dry_run:
                    storage.record_notification(key, "Polymarket 아침 브리핑", observed_at)
        else:
            notify(cfg.notification, message, dry_run=effective_dry_run, attachments=attachments)
        storage.insert_snapshots(outcomes, observed_at)


@app.command("fetch-watchlist")
def fetch_watchlist(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml"),
) -> None:
    cfg = load_config(config)
    with PolymarketClient(cfg.polymarket) as client:
        outcomes = []
        for slug in cfg.watchlist_slugs:
            try:
                outcomes.extend(normalize_event(client.get_event_by_slug(slug)))
            except RuntimeError as exc:
                typer.echo(f"skip {slug}: {exc}", err=True)
        typer.echo(
            json.dumps(
                [_as_dict(item) for item in outcomes],
                ensure_ascii=False,
                default=str,
                indent=2,
            )
        )


@app.command()
def discover(config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml")) -> None:
    cfg = load_config(config)
    observed_at = utc_now()
    with PolymarketClient(cfg.polymarket) as client:
        events = client.list_active_events(limit=cfg.discovery.max_events)
        outcomes = _filter_discovery(
            normalize_events(events),
            cfg.discovery.min_volume_24h,
        )
        scored = score_outcomes(outcomes, {}, cfg, observed_at)[: cfg.scoring.max_items]
        for item in scored:
            typer.echo(f"{item.score:5.1f} {item.outcome.event_title} / {item.outcome.outcome}")


@app.command("test-notify")
def test_notify(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml"),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    cfg = load_config(config)
    notify(cfg.notification, "테스트 알림입니다", dry_run=dry_run)


def _fetch_all(client: PolymarketClient, cfg) -> list[NormalizedOutcome]:
    outcomes: list[NormalizedOutcome] = []
    for slug in cfg.watchlist_slugs:
        try:
            outcomes.extend(normalize_event(client.get_event_by_slug(slug)))
        except RuntimeError as exc:
            typer.echo(f"skip watchlist {slug}: {exc}", err=True)
    if cfg.discovery.enabled:
        try:
            events = client.list_active_events(limit=cfg.discovery.max_events)
            outcomes.extend(
                _filter_discovery(
                    normalize_events(events),
                    cfg.discovery.min_volume_24h,
                )
            )
        except RuntimeError as exc:
            typer.echo(f"skip discovery: {exc}", err=True)
    return _dedupe_outcomes(outcomes)


def _calculate_deltas(
    client: PolymarketClient,
    storage: BriefingStorage,
    outcomes: list[NormalizedOutcome],
    observed_at,
    watchlist_slugs: set[str],
) -> dict[tuple[str, str | None, str], float | None]:
    deltas = {}
    start = int((observed_at - timedelta(hours=26)).timestamp())
    end = int(observed_at.timestamp())
    for outcome in outcomes:
        delta = None
        use_clob_history = outcome.event_slug in watchlist_slugs
        if use_clob_history and outcome.token_id and outcome.probability is not None:
            try:
                history = client.get_price_history(outcome.token_id, start, end)
                prices = history.get("history") or history.get("prices") or []
                if prices:
                    first = prices[0].get("p") if isinstance(prices[0], dict) else None
                    old_probability = float(first)
                    delta = (outcome.probability - old_probability) * 100
            except Exception:
                delta = None
        if delta is None:
            delta = calculate_snapshot_delta_pp(storage, outcome, observed_at)
        deltas[_key(outcome)] = delta
    return deltas


def _filter_discovery(
    outcomes: list[NormalizedOutcome],
    min_volume_24h: float,
) -> list[NormalizedOutcome]:
    return [
        item
        for item in outcomes
        if (item.volume_24h or item.volume or 0) >= min_volume_24h and item.closed is not True
    ]


def _dedupe_outcomes(outcomes: list[NormalizedOutcome]) -> list[NormalizedOutcome]:
    seen = set()
    deduped = []
    for item in outcomes:
        key = _key(item)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _select_items(
    scored,
    watchlist_slugs: set[str],
    min_score: float,
):
    grouped: dict[str, list] = {}
    for item in scored:
        if item.score < min_score and item.outcome.event_slug not in watchlist_slugs:
            continue
        grouped.setdefault(item.outcome.event_slug, []).append(item)

    event_order = sorted(
        grouped,
        key=lambda slug: (
            0 if slug in watchlist_slugs else 1,
            -max(item.score for item in grouped[slug]),
        ),
    )
    selected = []
    for slug in event_order:
        selected.extend(_top_event_items(grouped[slug]))
    return selected


def _top_event_items(items: list, max_markets: int = 3) -> list:
    markets: dict[str | None, list] = {}
    for item in items:
        markets.setdefault(item.outcome.market_id, []).append(item)
    ordered_markets = sorted(
        markets.values(),
        key=lambda group: max(item.score for item in group),
        reverse=True,
    )
    selected = []
    for group in ordered_markets[:max_markets]:
        selected.extend(sorted(group, key=lambda item: item.outcome.outcome.lower() != "yes")[:2])
    return selected


def _key(outcome: NormalizedOutcome) -> tuple[str, str | None, str]:
    return (outcome.event_slug, outcome.market_id, outcome.outcome)


def _as_dict(outcome: NormalizedOutcome) -> dict[str, object]:
    return outcome.__dict__


if __name__ == "__main__":
    app()
