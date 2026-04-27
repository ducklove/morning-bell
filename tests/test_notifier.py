import httpx

from polymarket_briefing.config import NotificationSettings
from polymarket_briefing.notifier import notify, send_ntfy, send_telegram


def test_ntfy_request(httpx_mock):
    httpx_mock.add_response(method="POST", url="https://ntfy.sh/topic", status_code=200)
    send_ntfy("topic", "title", "hello", priority=4)
    request = httpx_mock.get_request()
    assert request.headers["Title"] == "title"
    assert request.content == b"hello"


def test_telegram_request(httpx_mock):
    httpx_mock.add_response(method="POST", url="https://api.telegram.org/bottoken/sendMessage")
    send_telegram("token", "chat", "hello")
    request = httpx_mock.get_request()
    assert request is not None
    assert httpx.Request


def test_dry_run_no_network(capsys):
    notify(NotificationSettings(), "hello", dry_run=True)
    assert "hello" in capsys.readouterr().out

