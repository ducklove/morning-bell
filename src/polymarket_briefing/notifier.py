from __future__ import annotations

import sys
import time
from collections.abc import Iterable
from pathlib import Path

import httpx

from polymarket_briefing.config import NotificationSettings
from polymarket_briefing.utils import read_secret

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# ntfy silently converts an over-long body into a downloadable attachment instead
# of returning an error, so the phone shows a file card rather than readable text.
# Staying under the limit ourselves is the only way to avoid that failure mode.
NTFY_MAX_BYTES = 4096
NTFY_SAFETY_MARGIN_BYTES = 64
NTFY_BODY_BUDGET_BYTES = NTFY_MAX_BYTES - NTFY_SAFETY_MARGIN_BYTES

NTFY_TRUNCATION_MARKER = "…(길이 제한으로 일부 항목 생략)"
NTFY_DISCLAIMER_LINE = "꼬리표: 정보 요약이며 투자 조언이 아닙니다."


def truncate_for_ntfy(message: str, budget: int = NTFY_BODY_BUDGET_BYTES) -> str:
    """Shrink ``message`` so its UTF-8 encoding never exceeds ``budget`` bytes.

    Whole trailing lines are dropped (never a partial line, never a partial
    multi-byte character) until the remainder plus the truncation marker fits.
    The legal disclaimer line is preserved as the last line when it was present
    in the input.
    """
    if _byte_length(message) <= budget:
        return message

    lines = message.split("\n")
    keep_disclaimer = any(line.strip() == NTFY_DISCLAIMER_LINE for line in lines)
    if keep_disclaimer:
        lines = [line for line in lines if line.strip() != NTFY_DISCLAIMER_LINE]

    tail_lines = [NTFY_TRUNCATION_MARKER]
    if keep_disclaimer:
        tail_lines.append(NTFY_DISCLAIMER_LINE)
    tail = "\n".join(tail_lines)
    if _byte_length(tail) > budget:
        # Pathological budget: no room even for the marker, so fall back to a
        # character-safe hard cut that still respects the byte ceiling.
        return _cut_to_bytes(message, budget)

    while lines:
        if not lines[-1].strip():
            lines.pop()
            continue
        candidate = "\n".join([*lines, tail])
        if _byte_length(candidate) <= budget:
            return candidate
        lines.pop()
    return tail


def send_ntfy(topic: str, title: str, message: str, priority: int = 3) -> None:
    url = f"https://ntfy.sh/{topic}"
    body = truncate_for_ntfy(message)
    if body != message:
        print(
            f"warning: ntfy body truncated from {_byte_length(message)} to "
            f"{_byte_length(body)} bytes (limit {NTFY_MAX_BYTES})",
            file=sys.stderr,
        )
    # ntfy reads header values as raw UTF-8 bytes, which httpx will only send
    # verbatim if given `bytes` — a plain `str` with non-ASCII characters
    # raises UnicodeEncodeError since HTTP headers are ASCII by default.
    headers = {"Title": title.encode("utf-8"), "Priority": str(priority).encode("ascii")}
    response = _post_with_retries(url, content=body.encode("utf-8"), headers=headers, timeout=20)
    response.raise_for_status()


def send_telegram(bot_token: str, chat_id: str, message: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
    response = _post_with_retries(url, json=payload, timeout=20)
    response.raise_for_status()


def send_telegram_photo(bot_token: str, chat_id: str, image_path: Path, caption: str = "") -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    image_bytes = image_path.read_bytes()
    response = _post_with_retries(
        url,
        data={"chat_id": chat_id, "caption": caption},
        files={"photo": (image_path.name, image_bytes, "image/png")},
        timeout=30,
    )
    response.raise_for_status()


def notify(
    settings: NotificationSettings,
    message: str,
    dry_run: bool = False,
    attachments: Iterable[Path] | None = None,
) -> None:
    if dry_run:
        print(message)
        for attachment in attachments or []:
            print(f"[chart] {attachment}")
        return
    provider = settings.provider.lower()
    if provider == "ntfy":
        ntfy = settings.ntfy
        topic = _secret(str(ntfy.get("topic_env", "NTFY_TOPIC")))
        if not topic:
            raise RuntimeError("NTFY topic environment variable is not set")
        send_ntfy(
            topic=topic,
            title=str(ntfy.get("title", "Polymarket 아침 브리핑")),
            message=message,
            priority=int(ntfy.get("priority", 3)),
        )
        return
    if provider == "telegram":
        telegram = settings.telegram
        bot_token = _secret(str(telegram.get("bot_token_env", "TELEGRAM_BOT_TOKEN")))
        chat_id = _secret(str(telegram.get("chat_id_env", "TELEGRAM_CHAT_ID")))
        if not bot_token or not chat_id:
            raise RuntimeError("Telegram environment variables are not set")
        send_telegram(bot_token, chat_id, message)
        for attachment in attachments or []:
            try:
                send_telegram_photo(bot_token, chat_id, Path(attachment))
            except httpx.HTTPError as exc:
                print(f"warning: Telegram chart send failed: {exc}", file=sys.stderr)
        return
    raise RuntimeError(f"Unsupported notification provider: {settings.provider}")


def _byte_length(text: str) -> int:
    return len(text.encode("utf-8"))


def _cut_to_bytes(text: str, budget: int) -> str:
    # Decoding with "ignore" drops any trailing partial multi-byte character.
    return text.encode("utf-8")[:budget].decode("utf-8", "ignore")


def _secret(name: str) -> str | None:
    aliases = ("ntfy",) if name == "NTFY_TOPIC" else ()
    return read_secret(name, *aliases)


def _post_with_retries(url: str, attempts: int = 3, **kwargs) -> httpx.Response:
    last_error: httpx.HTTPError | None = None
    last_response: httpx.Response | None = None
    for attempt in range(attempts):
        try:
            response = httpx.post(url, **kwargs)
        except httpx.HTTPError as exc:
            last_error = exc
        else:
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response
            last_response = response
        if attempt + 1 < attempts:
            time.sleep(1.5 * (2**attempt))
    if last_response is not None:
        return last_response
    raise last_error or RuntimeError("HTTP request failed")
