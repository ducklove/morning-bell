from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from polymarket_briefing.models import ScoredOutcome
from polymarket_briefing.polymarket_client import PolymarketClient


def build_price_charts(
    client: PolymarketClient,
    items: list[ScoredOutcome],
    observed_at: datetime,
    output_dir: str = "state/charts",
    max_charts: int = 3,
) -> list[Path]:
    chart_items = _chart_candidates(items)[:max_charts]
    paths: list[Path] = []
    for item in chart_items:
        if not item.outcome.token_id:
            continue
        try:
            path = _build_chart(client, item, observed_at, output_dir)
        except Exception:
            continue
        if path:
            paths.append(path)
    return paths


def _chart_candidates(items: list[ScoredOutcome]) -> list[ScoredOutcome]:
    seen_events: set[str] = set()
    candidates: list[ScoredOutcome] = []
    for item in items:
        if item.outcome.event_slug in seen_events:
            continue
        if item.outcome.outcome.lower() != "yes":
            continue
        if item.outcome.token_id is None:
            continue
        seen_events.add(item.outcome.event_slug)
        candidates.append(item)
    return candidates


def _build_chart(
    client: PolymarketClient,
    item: ScoredOutcome,
    observed_at: datetime,
    output_dir: str,
) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    start_ts = int((observed_at - timedelta(days=7)).timestamp())
    end_ts = int(observed_at.timestamp())
    history = client.get_price_history(item.outcome.token_id or "", start_ts, end_ts, interval="1d")
    points = _history_points(history)
    if item.outcome.probability is not None:
        points.append((observed_at.replace(tzinfo=None), item.outcome.probability))
    if len(points) < 2:
        return None

    x_values = [point[0] for point in points]
    y_values = [point[1] * 100 for point in points]
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    file_path = output_path / f"{item.outcome.event_slug}-{item.outcome.market_id}.png"

    fig, ax = plt.subplots(figsize=(7, 3.8), dpi=160)
    ax.plot(x_values, y_values, color="#2563eb", linewidth=2.4)
    ax.fill_between(x_values, y_values, color="#bfdbfe", alpha=0.45)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Yes probability (%)")
    ax.set_title(_chart_title(item), loc="left", fontsize=11, pad=12)
    ax.grid(True, axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.autofmt_xdate(rotation=20)
    fig.tight_layout()
    fig.savefig(file_path)
    plt.close(fig)
    return file_path


def _history_points(history: dict) -> list[tuple[datetime, float]]:
    raw_points = history.get("history") or history.get("prices") or []
    points: list[tuple[datetime, float]] = []
    for raw in raw_points:
        if not isinstance(raw, dict):
            continue
        timestamp = raw.get("t") or raw.get("timestamp")
        price = raw.get("p") or raw.get("price")
        if timestamp is None or price is None:
            continue
        try:
            points.append((datetime.fromtimestamp(float(timestamp)), float(price)))
        except (TypeError, ValueError, OSError):
            continue
    return points


def _chart_title(item: ScoredOutcome) -> str:
    question = item.outcome.market_question or item.outcome.event_title
    return f"{question} - Yes"
