from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from polymarket_briefing.models import ScoredOutcome
from polymarket_briefing.utils import pct, pp


def summarize(items: list[ScoredOutcome], max_items: int, timezone_name: str = "Asia/Seoul") -> str:
    local_now = datetime.now(ZoneInfo(timezone_name))
    lines = [f"[Polymarket 아침 브리핑 | {local_now:%Y-%m-%d}]", ""]
    grouped: dict[tuple[str, str | None], list[ScoredOutcome]] = defaultdict(list)
    for item in items:
        key = (item.outcome.event_slug, item.outcome.market_id)
        if len(grouped) < max_items or key in grouped:
            grouped[key].append(item)
        if len(grouped) >= max_items and key not in grouped:
            break

    for index, group in enumerate(grouped.values(), start=1):
        top = group[0]
        outcome = top.outcome
        lines.append(f"{index}) {outcome.event_title}")
        facts = ", ".join(
            f"{item.outcome.outcome} {pct(item.outcome.probability)}{pp(item.delta_24h_pp)}"
            for item in sorted(
                group, key=lambda item: item.outcome.probability or 0, reverse=True
            )[:4]
        )
        lines.append(facts or f"거래량 {outcome.volume_24h or outcome.volume or 0:.0f}")
        lines.append(f"왜 봄: {' + '.join(top.reasons)}")
        lines.append(f"링크: {outcome.url}")
        lines.append("")

    if not grouped:
        lines.append("오늘 설정 기준을 넘는 관심 시장이 없습니다.")
        lines.append("")
    lines.append("꼬리표: 정보 요약이며 투자 조언이 아닙니다.")
    return "\n".join(lines)
