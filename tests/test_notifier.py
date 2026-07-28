import json

from polymarket_briefing.config import NotificationSettings
from polymarket_briefing.notifier import (
    NTFY_DISCLAIMER_LINE,
    NTFY_MAX_BYTES,
    NTFY_TRUNCATION_MARKER,
    _secret,
    notify,
    send_ntfy,
    send_telegram,
    truncate_for_ntfy,
)


def _long_korean_briefing(lines: int = 60) -> str:
    body = "\n".join(
        f"{index}. 대통령 선거 결과 예측 시장 확률이 크게 움직였습니다 상승 폭 확대"
        for index in range(lines)
    )
    return f"오늘의 브리핑\n{body}\n{NTFY_DISCLAIMER_LINE}"


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


def test_truncate_short_message_is_byte_identical():
    message = f"짧은 브리핑입니다\n항목 하나\n{NTFY_DISCLAIMER_LINE}"
    assert truncate_for_ntfy(message) == message
    assert truncate_for_ntfy(message).encode("utf-8") == message.encode("utf-8")


def test_truncate_long_message_fits_byte_budget():
    message = _long_korean_briefing()
    assert len(message.encode("utf-8")) > NTFY_MAX_BYTES

    truncated = truncate_for_ntfy(message)
    encoded = truncated.encode("utf-8")

    assert len(encoded) <= NTFY_MAX_BYTES
    assert NTFY_TRUNCATION_MARKER in truncated
    # Whole lines only: every surviving body line must be an original line.
    original_lines = set(message.split("\n"))
    kept = [line for line in truncated.split("\n") if line != NTFY_TRUNCATION_MARKER]
    assert all(line in original_lines for line in kept)


def test_truncate_preserves_disclaimer_as_last_line():
    truncated = truncate_for_ntfy(_long_korean_briefing())
    lines = truncated.split("\n")
    assert lines[-1] == NTFY_DISCLAIMER_LINE
    assert lines[-2] == NTFY_TRUNCATION_MARKER
    assert lines.count(NTFY_DISCLAIMER_LINE) == 1


def test_truncate_result_decodes_cleanly_as_utf8():
    encoded = truncate_for_ntfy(_long_korean_briefing()).encode("utf-8")
    # strict decode raises if a multi-byte character was split.
    assert encoded.decode("utf-8").endswith(NTFY_DISCLAIMER_LINE)


def test_truncate_respects_tight_budget_without_disclaimer():
    message = "\n".join(f"{index}번 항목 한국어 문장" for index in range(50))
    truncated = truncate_for_ntfy(message, budget=80)
    assert len(truncated.encode("utf-8")) <= 80
    assert truncated.encode("utf-8").decode("utf-8").endswith(NTFY_TRUNCATION_MARKER)


def test_ntfy_posts_truncated_body_and_warns(httpx_mock, capsys):
    httpx_mock.add_response(method="POST", url="https://ntfy.sh/topic", status_code=200)
    message = _long_korean_briefing()

    send_ntfy("topic", "title", message)

    request = httpx_mock.get_request()
    assert len(request.content) <= NTFY_MAX_BYTES
    assert request.content == truncate_for_ntfy(message).encode("utf-8")
    assert "warning: ntfy body truncated" in capsys.readouterr().err


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
