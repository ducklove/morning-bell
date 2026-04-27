from __future__ import annotations

import os
import re
from pathlib import Path

import httpx

from polymarket_briefing.models import ScoredOutcome
from polymarket_briefing.utils import pct, pp

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def load_openrouter_key(keys_path: str = "keys") -> str | None:
    env_key = os.environ.get("OPENROUTER_API_KEY")
    if env_key:
        return env_key
    path = Path(keys_path)
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip().lower() in {"openrouter", "openrouter_api_key"}:
            return value.strip().strip('"').strip("'")
    return None


def summarize_with_openrouter(
    items: list[ScoredOutcome],
    base_summary: str,
    api_key: str,
    model: str = "qwen/qwen3.6-flash",
) -> str:
    facts = "\n".join(_item_fact(item) for item in items[:10])
    prompt = f"""
다음은 Polymarket 공개 시장 데이터의 deterministic 선별/요약 결과입니다.
너는 한국어 아침 브리핑 문장을 다듬는 편집자입니다.

규칙:
- 투자 조언, 매수/매도 권유, 확정적 예측 금지.
- 기존 요약의 항목 수, 항목 순서, 링크, outcome 묶음을 유지할 것.
- Yes/No 또는 같은 market의 outcome을 별도 번호 항목으로 쪼개지 말 것.
- 아래 후보 안에서만 다듬고 새 사실을 만들지 말 것.
- 최대 7개 항목, 항목당 2~4줄.
- 변화량은 제공된 pp 값을 그대로 유지.
- 모든 항목에 링크 포함.
- 마지막 문장은 반드시 "꼬리표: 정보 요약이며 투자 조언이 아닙니다."

기존 요약:
{base_summary}

후보 데이터:
{facts}
""".strip()
    response = httpx.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ducklove/morning-bell",
            "X-Title": "morning-bell",
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You write concise Korean market briefings from supplied facts only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 900,
        },
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    ai_text = data["choices"][0]["message"]["content"].strip()
    if not _numbers_are_grounded(ai_text, base_summary):
        return base_summary
    return _ensure_required_lines(ai_text, base_summary)


def _item_fact(item: ScoredOutcome) -> str:
    outcome = item.outcome
    return (
        f"- score={item.score:.1f}; event={outcome.event_title}; "
        f"market={outcome.market_question}; outcome={outcome.outcome}; "
        f"probability={pct(outcome.probability)}; delta={pp(item.delta_24h_pp).strip() or 'n/a'}; "
        f"volume24h={outcome.volume_24h}; liquidity={outcome.liquidity}; "
        f"reasons={', '.join(item.reasons)}; url={outcome.url}"
    )


def _ensure_required_lines(ai_text: str, base_summary: str) -> str:
    lines = [line for line in ai_text.splitlines() if line.strip()]
    base_header = base_summary.splitlines()[0]
    if not lines or not lines[0].startswith("[Polymarket 아침 브리핑"):
        lines.insert(0, base_header)
    disclaimer = "꼬리표: 정보 요약이며 투자 조언이 아닙니다."
    if disclaimer not in lines[-1]:
        lines.append(disclaimer)
    return "\n\n".join(_paragraphs(lines))


def _numbers_are_grounded(ai_text: str, base_summary: str) -> bool:
    ai_numbers = set(re.findall(r"[+-]?\d+(?:\.\d+)?(?:%|pp)", ai_text))
    base_numbers = set(re.findall(r"[+-]?\d+(?:\.\d+)?(?:%|pp)", base_summary))
    return ai_numbers.issubset(base_numbers)


def _paragraphs(lines: list[str]) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("[") or line.startswith("꼬리표:") or line[:2].endswith(")"):
            if current:
                paragraphs.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs
