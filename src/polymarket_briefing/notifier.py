from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterable
from pathlib import Path

import httpx

from polymarket_briefing.config import NotificationSettings


def send_ntfy(topic: str, title: str, message: str, priority: int = 3) -> None:
    url = f"https://ntfy.sh/{topic}"
    headers = {"Title": title, "Priority": str(priority)}
    response = httpx.post(url, content=message.encode("utf-8"), headers=headers, timeout=20)
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
    value = os.environ.get(name)
    if value:
        return value
    aliases = {name, name.lower()}
    if name == "NTFY_TOPIC":
        aliases.add("ntfy")
    path = Path("keys")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        if key.strip() in aliases:
            return raw_value.strip().strip('"').strip("'")
    return None


def _post_with_retries(url: str, attempts: int = 3, **kwargs) -> httpx.Response:
    last_error: httpx.HTTPError | None = None
    for attempt in range(attempts):
        try:
            return httpx.post(url, **kwargs)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (2**attempt))
    raise last_error or RuntimeError("HTTP request failed")
