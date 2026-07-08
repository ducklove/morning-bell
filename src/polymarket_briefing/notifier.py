from __future__ import annotations

import sys
import time
from collections.abc import Iterable
from pathlib import Path

import httpx

from polymarket_briefing.config import NotificationSettings
from polymarket_briefing.utils import read_secret

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def send_ntfy(topic: str, title: str, message: str, priority: int = 3) -> None:
    url = f"https://ntfy.sh/{topic}"
    # ntfy reads header values as raw UTF-8 bytes, which httpx will only send
    # verbatim if given `bytes` — a plain `str` with non-ASCII characters
    # raises UnicodeEncodeError since HTTP headers are ASCII by default.
    headers = {"Title": title.encode("utf-8"), "Priority": str(priority).encode("ascii")}
    response = _post_with_retries(
        url, content=message.encode("utf-8"), headers=headers, timeout=20
    )
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
