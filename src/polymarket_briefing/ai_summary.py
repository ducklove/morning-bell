from __future__ import annotations

import re
import sys
import time

import httpx

from polymarket_briefing.models import ScoredOutcome
from polymarket_briefing.utils import pct, pp, read_secret

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DISCLAIMER_LINE = "꼬리표: 정보 요약이며 투자 조언이 아닙니다."


def load_openrouter_key(keys_path: str = "keys") -> str | None:
    return read_secret("OPENROUTER_API_KEY", "openrouter", keys_path=keys_path)


def summarize_with_openrouter(
    items: list[ScoredOutcome],
    base_summary: str,
    api_key: str,
    model: str = "qwen/qwen3.6-flash",
    max_retries: int = 3,
    timeout_seconds: float = 45,
    backoff_seconds: float = 1.5,
) -> str:
    """Return an LLM-polished briefing, or ``base_summary`` when anything goes wrong.

    This function never raises. The morning run must survive a dead endpoint, a
    malformed payload or a model that re-associates numbers with the wrong
    subject; in every one of those cases the deterministic summary is returned
    unchanged and a one-line reason is printed to stderr.
    """
    try:
        response = _post_openrouter(
            api_key=api_key,
            model=model,
            prompt=_build_prompt(items, base_summary),
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            backoff_seconds=backoff_seconds,
        )
        if response is None:
            return base_summary
        ai_text = _response_text(response)
        if ai_text is None:
            return base_summary
        if not _numbers_are_grounded(ai_text, base_summary):
            _warn("numbers are not grounded in the deterministic summary")
            return base_summary
        return _ensure_required_lines(ai_text, base_summary)
    except Exception as exc:  # the briefing must never die on a summary problem
        _warn(f"unexpected {type(exc).__name__}")
        return base_summary


def _warn(reason: str) -> None:
    print(f"warning: AI summary unavailable, using base summary: {reason}", file=sys.stderr)


def _build_prompt(items: list[ScoredOutcome], base_summary: str) -> str:
    facts = "\n".join(_item_fact(item) for item in items[:10])
    return f"""
다음은 Polymarket 공개 시장 데이터의 deterministic 선별/요약 결과입니다.
너는 한국어 아침 브리핑 문장을 다듬는 편집자입니다.

규칙:
- 영어 제목, 질문, outcome 표기는 자연스러운 한국어로 번역할 것. Yes는 예, No는 아니오로 쓸 것.
- 투자 조언, 매수/매도 권유, 확정적 예측 금지.
- 기존 요약의 항목 수, 항목 순서, 링크, outcome 묶음을 유지할 것.
- Yes/No 또는 같은 market의 outcome을 별도 번호 항목으로 쪼개지 말 것.
- 아래 후보 안에서만 다듬고 새 사실을 만들지 말 것.
- 최대 7개 항목, 항목당 2~4줄.
- "해설:", "왜 봄:", "링크:"는 각각 반드시 별도의 줄로 출력할 것. 한 줄에 합치지 말 것.
- 변화량은 제공된 pp 값을 그대로 유지.
- 숫자는 반드시 원래 대상(기업/후보) 옆에 그대로 둘 것. 대상끼리 숫자를 바꾸지 말 것.
- 모든 항목에 링크 포함.
- 마지막 문장은 반드시 "{DISCLAIMER_LINE}"

기존 요약:
{base_summary}

후보 데이터:
{facts}
""".strip()


def _post_openrouter(
    api_key: str,
    model: str,
    prompt: str,
    max_retries: int,
    timeout_seconds: float,
    backoff_seconds: float,
) -> httpx.Response | None:
    """POST to OpenRouter, retrying transient errors. Returns ``None`` on failure."""
    attempts = max(1, max_retries)
    for attempt in range(1, attempts + 1):
        try:
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
                            "content": "제공된 사실만 사용해 짧은 한국어 시장 브리핑을 씁니다.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1600,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError) as exc:
            if attempt == attempts:
                _warn(f"request failed after {attempts} attempt(s) ({_describe(exc)})")
                return None
            time.sleep(backoff_seconds * attempt)
    return None


def _describe(exc: Exception) -> str:
    """One-line description; httpx exception messages are multi-line."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def _response_text(response: httpx.Response) -> str | None:
    """Pull the assistant message out of an OpenRouter payload, or ``None``."""
    try:
        data = response.json()
    except ValueError:
        _warn("response body is not JSON")
        return None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        _warn("response has no choices[0].message.content")
        return None
    if not isinstance(content, str) or not content.strip():
        _warn("response content is empty")
        return None
    return content.strip()


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
    if DISCLAIMER_LINE not in lines[-1]:
        lines.append(DISCLAIMER_LINE)
    return "\n\n".join(_paragraphs(lines))


# --- grounding guard ---------------------------------------------------------
#
# The model is asked to rewrite English titles into natural Korean, so the words
# around a number legitimately change. What must NOT change is which subject a
# number belongs to. Membership alone ("every number in the AI text also exists
# in the base summary") is blind to re-association: swapping two probabilities
# between two companies keeps the token set identical. So each number is also
# attributed to an anchor - a capitalised Latin token such as `Apple` or
# `NVIDIA`, which survives translation because proper nouns are usually kept -
# and the anchor -> numbers mapping of the AI text must not contradict the base.

_NUMBER_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*(%|pp)")
_ANCHOR_RE = re.compile(r"[A-Za-z][A-Za-z0-9&'’.\-]*")
_URL_RE = re.compile(r"https?://\S+")
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
_ITEM_MARKER_RE = re.compile(r"^[ \t]*\d+[).]", re.MULTILINE)

# Function words and briefing boilerplate: shared between items, so they carry
# no subject identity and would only cause spurious contradictions.
_ANCHOR_STOPWORDS = frozenset(
    {
        "ai", "an", "and", "any", "apr", "april", "are", "as", "at", "aug", "august",
        "be", "before", "best", "between", "by", "cap", "can", "company", "dec",
        "december", "do", "does", "end", "feb", "february", "for", "from", "has",
        "have", "how", "http", "https", "if", "in", "is", "it", "jan", "january",
        "jul", "july", "jun", "june", "many", "mar", "march", "market", "may",
        "model", "month", "more", "most", "new", "no", "not", "nov", "november",
        "oct", "october", "of", "on", "or", "over", "polymarket", "price",
        "probability", "score", "sep", "september", "than", "that", "the", "there",
        "this", "to", "top", "total", "up", "us", "usd", "vs", "week", "what",
        "when", "which", "who", "will", "with", "world", "year", "yes",
    }
)


def _token(match: re.Match[str]) -> tuple[float, str]:
    return (round(float(match.group(1)), 1), match.group(2))


def _numeric_tokens(text: str) -> set[tuple[float, str]]:
    return {_token(match) for match in _NUMBER_RE.finditer(text)}


def _anchor_key(token: str) -> str | None:
    cleaned = token.strip(".-'’&_")
    if len(cleaned) < 2 or not any(char.isupper() for char in cleaned):
        return None
    key = cleaned.casefold()
    if key in _ANCHOR_STOPWORDS:
        return None
    return key


def _anchors(block: str) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for match in _ANCHOR_RE.finditer(block):
        key = _anchor_key(match.group(0))
        if key is not None:
            found.append((match.start(), match.end(), key))
    return found


def _blocks(text: str) -> list[str]:
    """Split into per-item blocks so attribution never crosses an item boundary.

    URLs are dropped first: their slugs repeat entity names far away from the
    numbers they would otherwise be attributed to.
    """
    cleaned = _URL_RE.sub(" ", text)
    blocks: list[str] = []
    for chunk in _BLANK_LINE_RE.split(cleaned):
        marks = {match.start() for match in _ITEM_MARKER_RE.finditer(chunk)}
        bounds = sorted({0, len(chunk)} | marks)
        for start, end in zip(bounds, bounds[1:], strict=False):
            piece = chunk[start:end]
            if piece.strip():
                blocks.append(piece)
    return blocks


def _nearest_anchor(anchors: list[tuple[int, int, str]], position: int) -> str | None:
    """The anchor a reader would attach this number to: the nearest one before it."""
    preceding = [anchor for anchor in anchors if anchor[1] <= position]
    if preceding:
        return max(preceding, key=lambda anchor: anchor[1])[2]
    following = [anchor for anchor in anchors if anchor[0] >= position]
    if following:
        return min(following, key=lambda anchor: anchor[0])[2]
    return None


def _anchored_numbers(text: str) -> dict[str, set[tuple[float, str]]]:
    mapping: dict[str, set[tuple[float, str]]] = {}
    for block in _blocks(text):
        anchors = _anchors(block)
        if not anchors:
            continue
        for match in _NUMBER_RE.finditer(block):
            anchor = _nearest_anchor(anchors, match.start())
            if anchor is None:
                continue
            mapping.setdefault(anchor, set()).add(_token(match))
    return mapping


def _pairings_are_grounded(ai_text: str, base_summary: str) -> bool:
    """False when the AI text hands a subject a number the base gave to someone else."""
    base_pairs = _anchored_numbers(base_summary)
    for anchor, numbers in _anchored_numbers(ai_text).items():
        allowed = base_pairs.get(anchor)
        if not allowed:
            # Subject absent from the base (e.g. translated into Hangul, or a
            # header word); membership checking is all the evidence available.
            continue
        if not numbers.issubset(allowed):
            return False
    return True


def _numbers_are_grounded(ai_text: str, base_summary: str) -> bool:
    """Fail closed: only text whose numbers *and* number/subject pairs match passes."""
    if not ai_text.strip():
        return False
    if not _numeric_tokens(ai_text).issubset(_numeric_tokens(base_summary)):
        return False
    return _pairings_are_grounded(ai_text, base_summary)


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
