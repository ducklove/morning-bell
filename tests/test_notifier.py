import json

from polymarket_briefing.config import NotificationSettings
from polymarket_briefing.notifier import _secret, notify, send_ntfy, send_telegram


def test_ntfy_request(httpx_mock):
    httpx_mock.add_response(method="POST", url="https://ntfy.sh/topic", status_code=200)
    send_ntfy("topic", "title", "hello", priority=4)
    request = httpx_mock.get_request()
    assert request.headers["Title"] == "title"
    assert request.content == b"hello"


def test_ntfy_request_with_korean_title_does_not_crash(httpx_mock):
    httpx_mock.add_response(method="POST", url="https://ntfy.sh/topic", status_code=200)
    send_ntfy("topic", "Polymarket 아침 브리핑", "hello", priority=3)
    request = httpx_mock.get_request()
    assert dict(request.headers.raw)[b"Title"] == "Polymarket 아침 브리핑".encode()


def test_ntfy_retries_on_retryable_status(httpx_mock, monkeypatch):
    monkeypatch.setattr("polymarket_briefing.notifier.time.sleep", lambda _seconds: None)
    httpx_mock.add_response(method="POST", url="https://ntfy.sh/topic", status_code=503)
    httpx_mock.add_response(method="POST", url="https://ntfy.sh/topic", status_code=200)
    send_ntfy("topic", "title", "hello")
    assert len(httpx_mock.get_requests()) == 2


def test_telegram_request(httpx_mock):
    httpx_mock.add_response(method="POST", url="https://api.telegram.org/bottoken/sendMessage")
    send_telegram("token", "chat", "hello")
    request = httpx_mock.get_request()
    assert request is not None
    body = json.loads(request.content)
    assert body == {"chat_id": "chat", "text": "hello", "disable_web_page_preview": True}


def test_dry_run_no_network(capsys):
    notify(NotificationSettings(), "hello", dry_run=True)
    assert "hello" in capsys.readouterr().out


def test_secret_reads_keys_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    (tmp_path / "keys").write_text("TELEGRAM_BOT_TOKEN=token-from-file\n", encoding="utf-8")
    assert _secret("TELEGRAM_BOT_TOKEN") == "token-from-file"
