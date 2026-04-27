from __future__ import annotations

import os

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
    response = httpx.post(url, json=payload, timeout=20)
    response.raise_for_status()


def notify(settings: NotificationSettings, message: str, dry_run: bool = False) -> None:
    if dry_run:
        print(message)
        return
    provider = settings.provider.lower()
    if provider == "ntfy":
        ntfy = settings.ntfy
        topic = os.environ.get(str(ntfy.get("topic_env", "NTFY_TOPIC")))
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
        bot_token = os.environ.get(str(telegram.get("bot_token_env", "TELEGRAM_BOT_TOKEN")))
        chat_id = os.environ.get(str(telegram.get("chat_id_env", "TELEGRAM_CHAT_ID")))
        if not bot_token or not chat_id:
            raise RuntimeError("Telegram environment variables are not set")
        send_telegram(bot_token, chat_id, message)
        return
    raise RuntimeError(f"Unsupported notification provider: {settings.provider}")
