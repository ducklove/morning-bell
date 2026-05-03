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
        lines.append(f"왜 봄: {' + '.join(_reason_label(reason) for reason in top.reasons)}")
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
    probability = pct(item.outcome.probability)
    delta = pp(item.delta_24h_pp)
    return f"{prefix}{_outcome_label(item.outcome.outcome)} {probability}{delta}"


def _market_label(question: str) -> str:
    patterns = [
        r"Will (.+) have the best AI model at the end of May 2026\?",
        r"Will (.+) be the largest company in the world by market cap on December 31\?",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, question)
        if match:
            return match.group(1)
    return _display_title(question, question)


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
        (
            r"How many ships transit the Strait of Hormuz week of (.+)",
            "{name} 주 호르무즈 해협 통항 선박 수",
        ),
        (
            r"Will ([0-9+-]+) ships transit the Strait of Hormuz between (.+)\?",
            "{name}척 통항: {body}",
        ),
        (
            r"(.+) vs\. (.+)",
            "{name} 대 {body}",
        ),
    ]
    for pattern, template in translations:
        match = re.fullmatch(pattern, source)
        if match:
            return _format_translation(match, template)
    return _rule_based_korean_title(source)


def _format_translation(match: Match[str], template: str | None) -> str:
    if template is None:
        return match.group(0)
    if "{name}" in template:
        values = {
            "name": _translate_market_phrase(match.group(1).rstrip("?")),
            "body": (
                _translate_market_phrase(match.group(2).rstrip("?"))
                if len(match.groups()) >= 2
                else ""
            ),
        }
        return template.format(**values)
    return template


def _rule_based_korean_title(source: str) -> str:
    cleaned = source.strip()
    normalized = cleaned.rstrip("?")
    generic_patterns: list[tuple[str, str]] = [
        (r"Will (.+) win (?:the )?(.+)", "{name}가 {body}에서 승리할까?"),
        (r"Who will win (?:the )?(.+)", "{body}의 승자는?"),
        (r"Which company will (.+)", "어느 기업이 {body}?"),
        (r"Which company has (.+)", "{body}를 보유한 기업은?"),
        (r"Will there be (.+)", "{body}이 발생할까?"),
        (r"Will (.+) have (.+)", "{name}가 {body}를 보유할까?"),
        (r"Will (.+) be (.+)", "{name}가 {body}일까?"),
        (r"Will (.+) (.+)", "{name}가 {body}할까?"),
    ]
    for pattern, template in generic_patterns:
        match = re.fullmatch(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        if "{name}" in template:
            return template.format(
                name=match.group(1),
                body=_translate_market_phrase(match.group(2)),
            )
        return template.format(body=_translate_market_phrase(match.group(1)))
    return _translate_market_phrase(normalized)


def _translate_market_phrase(text: str) -> str:
    phrase = text.strip()
    replacements = [
        (r"\bat the end of May 2026\b", "2026년 5월 말에"),
        (r"\bApril\b", "4월"),
        (r"\bApr\b", "4월"),
        (r"\bMay\b", "5월"),
        (r"\bJune\b", "6월"),
        (r"\bJun\b", "6월"),
        (r"\bJuly\b", "7월"),
        (r"\bJul\b", "7월"),
        (r"\bAugust\b", "8월"),
        (r"\bAug\b", "8월"),
        (r"\bSeptember\b", "9월"),
        (r"\bSep\b", "9월"),
        (r"\bOctober\b", "10월"),
        (r"\bOct\b", "10월"),
        (r"\bNovember\b", "11월"),
        (r"\bNov\b", "11월"),
        (r"\bDecember\b", "12월"),
        (r"\bDec\b", "12월"),
        (r"\bJanuary\b", "1월"),
        (r"\bJan\b", "1월"),
        (r"\bFebruary\b", "2월"),
        (r"\bFeb\b", "2월"),
        (r"\bMarch\b", "3월"),
        (r"\bMar\b", "3월"),
        (r"\bend of May\b", "5월 말"),
        (r"\bend of December 2026\b", "2026년 말"),
        (r"\bon December 31\b", "12월 31일에"),
        (r"\bby market cap\b", "시가총액 기준"),
        (r"\bmarket cap\b", "시가총액"),
        (r"\blargest company in the world\b", "세계 최대 기업"),
        (r"\bbest AI model\b", "최고 AI 모델"),
        (r"\bAI model\b", "AI 모델"),
        (r"\btraffic returns to normal\b", "통행이 정상화"),
        (r"\breturns to normal\b", "정상화"),
        (r"\bdiplomatic meeting\b", "외교 회담"),
        (r"\bceasefire\b", "휴전"),
        (r"\bblockade\b", "봉쇄"),
        (r"\bmayoral election\b", "시장 선거"),
        (r"\bpresidential election\b", "대통령 선거"),
        (r"\belection\b", "선거"),
        (r"\bSenate\b", "상원"),
        (r"\bHouse\b", "하원"),
        (r"\bCongress\b", "의회"),
        (r"\bDemocrat(?:ic)?\b", "민주당"),
        (r"\bRepublican\b", "공화당"),
        (r"\bgovernor\b", "주지사"),
        (r"\bIPO\b", "IPO"),
        (r"\bvaluation\b", "기업가치"),
        (r"\boil tanker\b", "유조선"),
        (r"\bshipping\b", "해운"),
    ]
    translated = phrase
    for pattern, replacement in replacements:
        translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)
    translated = translated.replace("  ", " ").strip()
    return translated


def _outcome_label(outcome: str) -> str:
    labels = {
        "yes": "예",
        "no": "아니오",
    }
    return labels.get(outcome.lower(), _translate_market_phrase(outcome))


def _reason_label(reason: str) -> str:
    labels = {
        "watchlist": "관심 목록",
        "24h 급변": "24시간 급변",
    }
    return labels.get(reason, reason)


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
    return f"예 확률이 24시간 전보다 {magnitude} {direction}. 현재는 {stance}입니다."


def _stance(probability: float) -> str:
    if probability >= 0.6:
        return "긍정 쪽이 우세"
    if probability <= 0.4:
        return "부정 쪽이 우세하지만 변화를 볼 만한 구간"
    return "찬반이 팽팽한 구간"
