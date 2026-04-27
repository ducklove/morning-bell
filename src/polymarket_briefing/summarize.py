from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from re import Match
from zoneinfo import ZoneInfo

from polymarket_briefing.models import ScoredOutcome
from polymarket_briefing.utils import pct, pp


def summarize(items: list[ScoredOutcome], max_items: int, timezone_name: str = "Asia/Seoul") -> str:
    local_now = datetime.now(ZoneInfo(timezone_name))
    lines = [f"[Polymarket 아침 브리핑 | {local_now:%Y-%m-%d}]", ""]
    grouped: dict[str, list[ScoredOutcome]] = defaultdict(list)
    for item in items:
        key = item.outcome.event_slug
        if len(grouped) < max_items or key in grouped:
            grouped[key].append(item)
        if len(grouped) >= max_items and key not in grouped:
            break

    for index, group in enumerate(grouped.values(), start=1):
        top = group[0]
        outcome = top.outcome
        has_multiple_markets = _has_multiple_markets(group)
        title_source = outcome.event_title if has_multiple_markets else outcome.market_question
        lines.append(f"{index}) {_display_title(outcome.event_title, title_source)}")
        ordered_group = _display_items(group)
        facts = "; ".join(
            _fact_line(item, has_multiple_markets) for item in ordered_group[:5]
        )
        lines.append(facts or f"거래량 {outcome.volume_24h or outcome.volume or 0:.0f}")
        explanation = _trend_explanation(ordered_group)
        if explanation:
            lines.append(f"해설: {explanation}")
        lines.append(f"왜 봄: {' + '.join(top.reasons)}")
        lines.append(f"링크: {outcome.url}")
        lines.append("")

    if not grouped:
        lines.append("오늘 설정 기준을 넘는 관심 시장이 없습니다.")
        lines.append("")
    lines.append("꼬리표: 정보 요약이며 투자 조언이 아닙니다.")
    return "\n".join(lines)


def _display_items(group: list[ScoredOutcome]) -> list[ScoredOutcome]:
    if _has_multiple_markets(group):
        yes_items = [item for item in group if item.outcome.outcome.lower() == "yes"]
        return sorted(yes_items or group, key=lambda item: item.score, reverse=True)
    return _display_order(group)


def _display_order(group: list[ScoredOutcome]) -> list[ScoredOutcome]:
    outcome_names = {item.outcome.outcome.lower() for item in group}
    if {"yes", "no"}.issubset(outcome_names):
        return sorted(
            group,
            key=lambda item: 0 if item.outcome.outcome.lower() == "yes" else 1,
        )
    return sorted(group, key=lambda item: item.outcome.probability or 0, reverse=True)


def _has_multiple_markets(group: list[ScoredOutcome]) -> bool:
    return len({item.outcome.market_id for item in group}) > 1


def _fact_line(item: ScoredOutcome, include_market_label: bool) -> str:
    prefix = f"{_market_label(item.outcome.market_question)} " if include_market_label else ""
    return f"{prefix}{item.outcome.outcome} {pct(item.outcome.probability)}{pp(item.delta_24h_pp)}"


def _market_label(question: str) -> str:
    patterns = [
        r"Will (.+) have the best AI model at the end of May 2026\?",
        r"Will (.+) be the largest company in the world by market cap on December 31\?",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, question)
        if match:
            return match.group(1)
    return question


def _display_title(event_title: str, market_question: str) -> str:
    source = market_question if market_question and market_question != event_title else event_title
    translations: list[tuple[str, str | None]] = [
        (
            r"Which company has the best AI model end of May\?",
            "2026년 5월 말 최고 AI 모델 경쟁",
        ),
        (
            r"Will (.+) have the best AI model at the end of May 2026\?",
            "2026년 5월 말 최고 AI 모델 보유 후보: {name}",
        ),
        (
            r"Will (.+) be the largest company in the world by market cap on December 31\?",
            "12월 31일 세계 시가총액 1위 후보: {name}",
        ),
        (
            r"Strait of Hormuz traffic returns to normal by end of May\?",
            "5월 말까지 호르무즈 해협 통행이 정상화될까?",
        ),
        (
            r"Largest Company end of December 2026\?",
            "2026년 말 시가총액 1위 기업은?",
        ),
    ]
    for pattern, template in translations:
        match = re.fullmatch(pattern, source)
        if match:
            return _format_translation(match, template)
    return source


def _format_translation(match: Match[str], template: str | None) -> str:
    if template is None:
        return match.group(0)
    if "{name}" in template:
        return template.format(name=match.group(1))
    return template


def _trend_explanation(group: list[ScoredOutcome]) -> str | None:
    yes_item = next((item for item in group if item.outcome.outcome.lower() == "yes"), None)
    if yes_item is None or yes_item.outcome.probability is None:
        return None
    probability = yes_item.outcome.probability
    delta = yes_item.delta_24h_pp
    stance = _stance(probability)
    if delta is None:
        return f"현재 시장은 {stance}로 보고 있습니다."
    if delta > 0:
        direction = "올랐습니다"
    elif delta < 0:
        direction = "내렸습니다"
    else:
        direction = "거의 변하지 않았습니다"
    magnitude = f"{abs(delta):.1f}pp"
    return f"Yes 확률이 24시간 전보다 {magnitude} {direction}. 현재는 {stance}입니다."


def _stance(probability: float) -> str:
    if probability >= 0.6:
        return "긍정 쪽이 우세"
    if probability <= 0.4:
        return "부정 쪽이 우세하지만 변화를 볼 만한 구간"
    return "찬반이 팽팽한 구간"
