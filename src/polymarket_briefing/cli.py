from __future__ import annotations

import contextlib
import json
import re
import sys
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import typer

from polymarket_briefing.ai_summary import load_openrouter_key, summarize_with_openrouter
from polymarket_briefing.charts import build_price_charts, history_points
from polymarket_briefing.config import AppConfig, load_config
from polymarket_briefing.models import (
    FetchResult,
    NormalizedOutcome,
    ReasonCode,
    ScoredOutcome,
    activity_volume,
    outcome_haystack,
    outcome_key,
)
from polymarket_briefing.normalize import normalize_event, normalize_events
from polymarket_briefing.notifier import notify, prepare_briefing
from polymarket_briefing.polymarket_client import PolymarketClient
from polymarket_briefing.scoring import contains_term, score_outcomes
from polymarket_briefing.storage import (
    BriefingStorage,
    calculate_snapshot_delta_pp,
    dedupe_key_for,
)
from polymarket_briefing.summarize import displayed_items, summarize
from polymarket_briefing.utils import utc_now


def _ensure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8")


_ensure_utf8_console()

# Ask the CLOB for a little more than 24h so a point on either side of the
# 24h mark exists; the reference point is then chosen by proximity.
CLOB_HISTORY_WINDOW_HOURS = 26
DELTA_TARGET_HOURS = 24
DELTA_TOLERANCE_HOURS = 6

# Price history costs one request per outcome, so cap how many we buy per run
# and spread them across events rather than draining the budget on one event
# that happens to have dozens of markets.
CLOB_DELTA_BUDGET = 60
CLOB_DELTA_MARKETS_PER_EVENT = 3

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml"),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    ai_summary: Annotated[
        bool | None,
        typer.Option("--ai-summary/--no-ai-summary"),
    ] = None,
    ai_model: Annotated[str | None, typer.Option("--ai-model")] = None,
) -> None:
    cfg = load_config(config)
    observed_at = utc_now()
    effective_dry_run = dry_run or cfg.notification.dry_run_default
    with (
        PolymarketClient(cfg.polymarket) as client,
        BriefingStorage(cfg.storage.path, read_only=effective_dry_run) as storage,
    ):
        fetched = _fetch_all(client, cfg)
        if fetched.failed_sources and not fetched.successful_sources:
            typer.echo(
                "오류: 모든 데이터 소스 조회에 실패했습니다. 브리핑을 발송하지 않습니다.",
                err=True,
            )
            raise typer.Exit(1)
        outcomes = fetched.outcomes
        watchlist_slugs = set(cfg.watchlist_slugs)
        sent_outcome_keys = storage.recently_sent_outcome_keys(
            observed_at, cfg.scoring.sent_penalty_days
        )
        sent_event_slugs = {event_slug for event_slug, _market_id, _outcome in sent_outcome_keys}
        # Score once on local snapshots to rank candidates, then spend the price
        # history budget on the leaders and score again with the real 24h moves.
        deltas = _snapshot_deltas(storage, outcomes, observed_at)
        provisional = score_outcomes(
            outcomes, deltas, cfg, observed_at, sent_outcome_keys, sent_event_slugs
        )
        deltas = _enrich_with_clob_deltas(
            client, provisional, deltas, observed_at, watchlist_slugs
        )
        scored = score_outcomes(
            outcomes, deltas, cfg, observed_at, sent_outcome_keys, sent_event_slugs
        )
        selected = _select_items(scored, watchlist_slugs, cfg.scoring.min_score_to_notify)
        selected = _collapse_similar_events(selected, cfg.scoring.max_events_per_topic)
        selected = _limit_by_event_count(selected, cfg.scoring.max_items)
        selected = _hide_no_hope_outcomes(selected, cfg.scoring.min_probability_to_show)
        message = summarize(selected, cfg.scoring.max_items, cfg.timezone, observed_at=observed_at)
        use_ai_summary = cfg.ai_summary.enabled if ai_summary is None else ai_summary
        api_key = load_openrouter_key() if use_ai_summary else None
        if use_ai_summary and not api_key:
            # A missing key must not cost the user their whole briefing; the
            # deterministic Korean summary is a usable, if clumsier, fallback.
            typer.echo("warning: no OpenRouter key found; using deterministic summary", err=True)
        if use_ai_summary and api_key:
            message = summarize_with_openrouter(
                selected,
                message,
                api_key,
                model=ai_model if ai_model else cfg.ai_summary.model,
                max_retries=cfg.ai_summary.max_retries,
                timeout_seconds=cfg.ai_summary.timeout_seconds,
                backoff_seconds=cfg.ai_summary.backoff_seconds,
            )
        # After the AI pass so the notice cannot be paraphrased away.
        message = _with_stale_watchlist_notice(message, fetched.closed_slugs)
        if fetched.failed_sources:
            message = _with_notice(
                message,
                f"[점검] 데이터 소스 {len(fetched.failed_sources)}개 조회 실패 · 일부 결과만 표시",
            )
        message, selected = prepare_briefing(message, displayed_items(selected))
        typer.echo(
            f"진단: 조회 성공 {fetched.successful_sources} / 실패 {len(fetched.failed_sources)} · "
            f"결과 {len(outcomes)}개 · 표시 {len({i.outcome.event_slug for i in selected})}건 · "
            f"변화량 {sum(i.delta_24h_pp is not None for i in selected)}/{len(selected)}개",
            err=True,
        )
        attachments = []
        if cfg.notification.provider.lower() == "telegram":
            attachments = build_price_charts(client, selected, observed_at)
        try:
            _deliver(
                cfg, storage, message, selected, observed_at, effective_dry_run, attachments
            )
        finally:
            # Snapshots are tomorrow's delta baseline, so persist them even when
            # delivery fails — otherwise one bad morning also blinds the next.
            if not effective_dry_run:
                storage.insert_snapshots(outcomes, observed_at)
                storage.prune_older_than(
                    observed_at - timedelta(days=cfg.storage.retention_days)
                )


def _deliver(
    cfg: AppConfig,
    storage: BriefingStorage,
    message: str,
    selected: list[ScoredOutcome],
    observed_at: datetime,
    effective_dry_run: bool,
    attachments: list[Path],
) -> None:
    key = _briefing_dedupe_key(observed_at, selected)
    if not effective_dry_run and storage.notification_sent(key):
        return
    notify(cfg.notification, message, dry_run=effective_dry_run, attachments=attachments)
    if effective_dry_run:
        return
    storage.record_delivery(
        key, "Polymarket 아침 브리핑", [item.outcome for item in selected], observed_at
    )


def _briefing_dedupe_key(observed_at: datetime, selected: list[ScoredOutcome]) -> str:
    """Derive one key from the whole briefing, not just its top item.

    Keying on `selected[0]` alone meant a day where only the lower items changed
    counted as a duplicate, while a 0.1pp wobble in the top item forced a resend.
    An empty briefing also needs a key so repeated runs do not resend it.
    """
    if not selected:
        return dedupe_key_for(observed_at, "", None, "empty", None, None)
    parts = [
        dedupe_key_for(
            observed_at,
            item.outcome.event_slug,
            item.outcome.market_id,
            item.outcome.outcome,
            item.outcome.probability,
            item.delta_24h_pp,
        )
        for item in selected
    ]
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


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


@app.command("validate-config")
def validate_config(
    config: Annotated[Path, typer.Option("--config")] = Path("config.yaml"),
) -> None:
    load_config(config)
    typer.echo("설정 검증 완료")


@app.command("backup-state")
def backup_state(
    output: Annotated[Path, typer.Option("--output")],
    config: Annotated[Path, typer.Option("--config")] = Path("config.yaml"),
) -> None:
    cfg = load_config(config)
    with BriefingStorage(cfg.storage.path) as storage:
        storage.backup_to(output.expanduser())
        typer.echo(f"상태 DB: {storage.path}; 백업: {output}")


@app.command()
def discover(config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml")) -> None:
    cfg = load_config(config)
    observed_at = utc_now()
    with PolymarketClient(cfg.polymarket) as client:
        events = _discover_events(client, cfg)
        outcomes = _filter_discovery(
            normalize_events(events),
            cfg.discovery.min_volume_24h,
            cfg.discovery.exclude_terms,
            include_closed=cfg.discovery.include_closed,
            active_only=cfg.discovery.include_active_only,
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


def _fetch_all(client: PolymarketClient, cfg: AppConfig) -> FetchResult:
    """Fetch watchlist + discovery outcomes, and report unusable watchlist slugs.

    A watchlist event that has fully resolved still returns HTTP 200, so it is
    dropped by `_filter_closed` without raising. Left unreported that looks
    identical to a healthy run, which is how the whole watchlist can go stale
    unnoticed — so surface those slugs to the caller.
    """
    outcomes: list[NormalizedOutcome] = []
    stale_slugs: list[str] = []
    failed_sources: list[str] = []
    successful_sources = 0
    for slug in cfg.watchlist_slugs:
        try:
            normalized = normalize_event(client.get_event_by_slug(slug))
            if not normalized:
                raise RuntimeError("시장 데이터가 없거나 응답 형식이 변경되었습니다")
            live = _filter_closed(normalized)
        except RuntimeError as exc:
            typer.echo(f"skip watchlist {slug}: {exc}", err=True)
            failed_sources.append(slug)
            continue
        successful_sources += 1
        if not live:
            typer.echo(f"warning: watchlist {slug} has no open markets", err=True)
            stale_slugs.append(slug)
        outcomes.extend(live)
    if cfg.discovery.enabled:
        try:
            events = _discover_events(client, cfg)
            normalized = normalize_events(events)
            if events and not normalized:
                raise RuntimeError("이벤트를 정규화할 수 없습니다")
            outcomes.extend(
                _filter_discovery(
                    normalized,
                    cfg.discovery.min_volume_24h,
                    cfg.discovery.exclude_terms,
                    include_closed=cfg.discovery.include_closed,
                    active_only=cfg.discovery.include_active_only,
                )
            )
            successful_sources += 1
        except RuntimeError as exc:
            typer.echo(f"skip discovery: {exc}", err=True)
            failed_sources.append("discovery")
    return FetchResult(_dedupe_outcomes(outcomes), stale_slugs, failed_sources, successful_sources)


def _discover_events(client: PolymarketClient, cfg: AppConfig) -> list[dict]:
    return client.list_active_events(
        limit=cfg.discovery.max_events,
        page_size=cfg.polymarket.page_size,
        active_only=cfg.discovery.include_active_only,
        include_closed=cfg.discovery.include_closed,
    )


def _with_stale_watchlist_notice(message: str, stale_slugs: list[str]) -> str:
    """Surface stale watchlist slugs in the briefing itself.

    stderr alone is invisible on a timer-driven run, so the notice has to ride
    along with the notification the user actually reads.
    """
    if not stale_slugs:
        return message
    # The detailed slugs are already in stderr; keep the phone notification compact.
    notice = f"[점검] 워치리스트 {len(stale_slugs)}개가 종료됨 · 목록 갱신 필요"
    return _with_notice(message, notice)


def _with_notice(message: str, notice: str) -> str:
    lines = message.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("꼬리표:"):
            lines[index:index] = [notice, ""]
            return "\n".join(lines)
    return "\n".join([*lines, notice])


def _snapshot_deltas(
    storage: BriefingStorage, outcomes: list[NormalizedOutcome], observed_at: datetime
) -> dict[tuple[str, str | None, str], float | None]:
    return {
        outcome_key(item): calculate_snapshot_delta_pp(storage, item, observed_at)
        for item in outcomes
    }


def _enrich_with_clob_deltas(
    client: PolymarketClient,
    provisional: list[ScoredOutcome],
    deltas: dict[tuple[str, str | None, str], float | None],
    observed_at: datetime,
    watchlist_slugs: set[str],
    budget: int = CLOB_DELTA_BUDGET,
) -> dict[tuple[str, str | None, str], float | None]:
    """Replace snapshot deltas with real CLOB history for the strongest candidates.

    A snapshot delta needs a prior run to compare against, so on a fresh database
    the change signal — the single heaviest scoring weight — is uniformly zero and
    the ranking silently degrades to volume and keywords. CLOB price history gives
    a true 24h move with no local state at all, but costs one request per outcome,
    so the budget goes to watchlist items first and then down the provisional
    ranking.
    """
    start = int((observed_at - timedelta(hours=CLOB_HISTORY_WINDOW_HOURS)).timestamp())
    end = int(observed_at.timestamp())
    target = observed_at - timedelta(hours=DELTA_TARGET_HOURS)
    enriched = dict(deltas)
    for item in _clob_delta_targets(provisional, watchlist_slugs, budget):
        outcome = item.outcome
        try:
            history = client.get_price_history(outcome.token_id or "", start, end)
        except Exception:
            continue
        reference = _reference_probability(history_points(history), target)
        if reference is not None and outcome.probability is not None:
            enriched[outcome_key(outcome)] = (outcome.probability - reference) * 100
    return enriched


def _clob_delta_targets(
    provisional: list[ScoredOutcome], watchlist_slugs: set[str], budget: int
) -> list[ScoredOutcome]:
    """Pick which outcomes are worth a price-history request.

    `provisional` arrives sorted by score, so keeping first-seen order preserves
    that ranking. Only the best outcome of each market is fetched, and only a few
    markets per event, because the briefing never shows more than that anyway.
    """
    best_per_market: dict[tuple[str, str | None], ScoredOutcome] = {}
    for item in provisional:
        outcome = item.outcome
        if not outcome.token_id or outcome.probability is None:
            continue
        best_per_market.setdefault((outcome.event_slug, outcome.market_id), item)

    per_event: dict[str, list[ScoredOutcome]] = {}
    for item in best_per_market.values():
        markets = per_event.setdefault(item.outcome.event_slug, [])
        if len(markets) < CLOB_DELTA_MARKETS_PER_EVENT:
            markets.append(item)

    watchlist_first = [
        item for slug, items in per_event.items() if slug in watchlist_slugs for item in items
    ]
    remainder = [
        item for slug, items in per_event.items() if slug not in watchlist_slugs for item in items
    ]
    return [*watchlist_first, *remainder][:budget]


def _reference_probability(
    points: list[tuple[datetime, float]], target: datetime
) -> float | None:
    """Return the observed price closest to `target`, or None if none is close.

    The CLOB window is requested wider than 24h so a point spanning the target
    exists. Taking `points[0]` would silently compare against the oldest point
    in that wider window — reporting a 26h move under a "24시간 전보다" label —
    so pick the nearest point and drop the delta when nothing lands in range.
    """
    if not points:
        return None
    nearest_at, nearest_price = min(
        points, key=lambda point: abs((point[0] - target).total_seconds())
    )
    if abs((nearest_at - target).total_seconds()) > DELTA_TOLERANCE_HOURS * 3600:
        return None
    return nearest_price


def _filter_closed(outcomes: list[NormalizedOutcome]) -> list[NormalizedOutcome]:
    return [item for item in outcomes if item.closed is not True]


def _filter_discovery(
    outcomes: list[NormalizedOutcome],
    min_volume_24h: float,
    exclude_terms: list[str] | None = None,
    *,
    include_closed: bool = False,
    active_only: bool = True,
) -> list[NormalizedOutcome]:
    exclude_terms = exclude_terms or []
    return [
        item
        for item in outcomes
        if activity_volume(item) >= min_volume_24h
        and (include_closed or item.closed is not True)
        and (not active_only or item.active is not False)
        and not _matches_excluded_interest(item, exclude_terms)
    ]


def _matches_excluded_interest(outcome: NormalizedOutcome, exclude_terms: list[str]) -> bool:
    haystack = outcome_haystack(outcome)
    return any(contains_term(haystack, term) for term in exclude_terms)


def _dedupe_outcomes(outcomes: list[NormalizedOutcome]) -> list[NormalizedOutcome]:
    seen = set()
    deduped = []
    for item in outcomes:
        key = outcome_key(item)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _select_items(
    scored: list[ScoredOutcome],
    watchlist_slugs: set[str],
    min_score: float,
) -> list[ScoredOutcome]:
    grouped: dict[str, list[ScoredOutcome]] = {}
    for item in scored:
        recently_sent = (
            ReasonCode.RECENTLY_SENT in item.reasons
            or ReasonCode.EVENT_RECENTLY_SENT in item.reasons
        )
        sharply_changed = ReasonCode.SHARP_CHANGE in item.reasons
        if item.score < min_score and (
            item.outcome.event_slug not in watchlist_slugs
            or (recently_sent and not sharply_changed)
        ):
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


def _top_event_items(items: list[ScoredOutcome], max_markets: int = 3) -> list[ScoredOutcome]:
    markets: dict[str | None, list[ScoredOutcome]] = {}
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


_TOPIC_NOISE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
    r"|\b\d+(?:st|nd|rd|th)?\b",
    flags=re.IGNORECASE,
)


def _topic_signature(title: str) -> str:
    """Collapse a title to the part that identifies its topic.

    "Largest Company end of July?" and "Largest Company end of August?" are the
    same recurring question with a different settlement date, and shipping both
    spends two of seven slots on one topic. Dates and numbers are what vary, so
    strip them and compare what is left. Deliberately an exact match on the
    remainder rather than a fuzzy score — wrongly merging two distinct markets
    hides information, which is worse than showing a near-duplicate.
    """
    cleaned = _TOPIC_NOISE.sub(" ", title.lower())
    return " ".join(re.findall(r"[a-z가-힣]+", cleaned))


def _collapse_similar_events(
    selected: list[ScoredOutcome], max_events_per_topic: int
) -> list[ScoredOutcome]:
    if max_events_per_topic <= 0:
        return selected
    kept_per_topic: dict[str, set[str]] = {}
    result = []
    for item in selected:
        signature = _topic_signature(item.outcome.event_title)
        slugs = kept_per_topic.setdefault(signature, set())
        if item.outcome.event_slug in slugs:
            result.append(item)
            continue
        if len(slugs) >= max_events_per_topic:
            continue
        slugs.add(item.outcome.event_slug)
        result.append(item)
    return result


def _hide_no_hope_outcomes(
    selected: list[ScoredOutcome], min_probability: float
) -> list[ScoredOutcome]:
    """Drop candidates too unlikely to be worth a line.

    A 0.1% outcome carries no information for a morning briefing. The first item
    of each event always survives, so filtering can never leave an event with a
    heading and no facts under it.
    """
    if min_probability <= 0:
        return selected
    seen_events: set[str] = set()
    result = []
    for item in selected:
        slug = item.outcome.event_slug
        is_first_of_event = slug not in seen_events
        seen_events.add(slug)
        probability = item.outcome.probability
        if is_first_of_event or probability is None or probability >= min_probability:
            result.append(item)
    return result


def _limit_by_event_count(selected: list[ScoredOutcome], max_events: int) -> list[ScoredOutcome]:
    """Truncate by distinct event count, not raw item count.

    `selected` is already ordered so a market's outcomes stay adjacent; cutting
    by item count could otherwise split a Yes/No pair mid-market.
    """
    seen_slugs: list[str] = []
    limited = []
    for item in selected:
        slug = item.outcome.event_slug
        if slug not in seen_slugs:
            if len(seen_slugs) >= max_events:
                break
            seen_slugs.append(slug)
        limited.append(item)
    return limited


def _as_dict(outcome: NormalizedOutcome) -> dict[str, object]:
    return outcome.__dict__


if __name__ == "__main__":
    app()
