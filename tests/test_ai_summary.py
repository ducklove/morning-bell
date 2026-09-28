from __future__ import annotations

from typing import Any

import pytest

from polymarket_briefing.ai_summary import (
    DISCLAIMER_LINE,
    OPENROUTER_URL,
    _apply_titles,
    load_openrouter_key,
    summarize_with_openrouter,
)
from polymarket_briefing.models import NormalizedOutcome, ScoredOutcome

BASE_SUMMARY = "\n".join(
    [
        "[Polymarket 아침 브리핑 | 2026-07-28]",
        "",
        "1) 12월 31일 세계 시가총액 1위 후보",
        "Apple 예 79.3% (+1.2pp); NVIDIA 예 20.5% (-1.2pp)",
        "해설: 예 확률이 24시간 전보다 1.2pp 올랐습니다. 현재는 긍정 쪽이 우세입니다.",
        "왜 봄: 관심 목록",
        "링크: https://polymarket.com/event/largest-company-december-31",
        "",
        DISCLAIMER_LINE,
    ]
)

MULTI_ITEM_BASE = "\n".join(
    [
        "[Polymarket 아침 브리핑 | 2026-07-28]",
        "",
        "1) 2026년 5월 말 최고 AI 모델 경쟁",
        "Google 예 41.0% (+3.0pp); OpenAI 예 32.5% (-2.0pp)",
        "링크: https://polymarket.com/event/best-ai-model-may",
        "",
        "2) 12월 31일 세계 시가총액 1위 후보",
        "Apple 예 79.3% (+1.2pp); NVIDIA 예 20.5% (-1.2pp)",
        "링크: https://polymarket.com/event/largest-company-december-31",
        "",
        DISCLAIMER_LINE,
    ]
)

CLEAN_AI_TEXT = "\n".join(
    [
        "[Polymarket 아침 브리핑 | 2026-07-28]",
        "",
        "1) 12월 31일 시가총액 1위 자리를 두고",
        "Apple이 79.3% (+1.2pp)로 앞서고, NVIDIA는 20.5% (-1.2pp)에 머물고 있습니다.",
        "왜 봄: 관심 목록",
        "링크: https://polymarket.com/event/largest-company-december-31",
        "",
        DISCLAIMER_LINE,
    ]
)


def _outcome(name: str = "Yes", probability: float = 0.793) -> NormalizedOutcome:
    return NormalizedOutcome(
        event_id="1",
        event_slug="largest-company-december-31",
        event_title="Largest Company end of December 2026?",
        market_id="10",
        market_slug="apple-largest",
        market_question=(
            "Will Apple be the largest company in the world by market cap on December 31?"
        ),
        outcome=name,
        probability=probability,
        token_id="t1",
        volume=100000.0,
        volume_24h=5000.0,
        liquidity=20000.0,
        end_date=None,
        active=True,
        closed=False,
        resolution_source=None,
        url="https://polymarket.com/event/largest-company-december-31",
    )


def _items() -> list[ScoredOutcome]:
    return [
        ScoredOutcome(outcome=_outcome(), score=12.0, delta_24h_pp=1.2, reasons=("watchlist",)),
    ]


def _completion(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("polymarket_briefing.ai_summary.time.sleep", lambda _seconds: None)


def _titles(title: str = "12월 31일 세계 시가총액 1위 기업은?") -> str:
    import json
    return json.dumps({"titles": [{"id": "largest-company-december-31", "title": title}]})


def test_only_titles_are_rewritten_and_all_facts_are_preserved(httpx_mock):
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(_titles()))
    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")
    assert "1) 12월 31일 세계 시가총액 1위 기업은?" in result
    assert [s for s in result.splitlines() if not s.startswith("1)")] == [
        s for s in BASE_SUMMARY.splitlines() if not s.startswith("1)")
    ]
    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer key"
    assert b"79.3%" not in request.content
    assert b"20.5%" not in request.content


@pytest.mark.parametrize("content", [
    "오늘은 특별한 움직임이 없습니다.",
    "애플 예 20.5% (-1.2pp); 엔비디아 예 79.3% (+1.2pp)",
    '{"titles": []}',
    '{"titles": [{"id": "wrong", "title": "12월 31일 질문"}]}',
    '{"titles": [{"id": "largest-company-december-31", "title": "날짜 누락"}]}',
    '{"titles": [{"id": "largest-company-december-31", "title": "12월 31일", "url": "wrong"}]}',
    _titles("12월 31일 https://polymarket.com/event/wrong"),
    _titles("12월 31일 질문\nApple 20.5%"),
    _titles("12월 31일 확률 상승"),
    _titles("13월 31일 질문"),
])
def test_invalid_or_unstructured_edits_fall_back(httpx_mock, content):
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(content))
    assert summarize_with_openrouter(_items(), BASE_SUMMARY, "key") == BASE_SUMMARY


def test_duplicate_ids_are_rejected():
    import json
    with pytest.raises(ValueError):
        _apply_titles(json.dumps({"titles": [
            {"id": "a", "title": "가"}, {"id": "a", "title": "나"},
        ]}), {"a": "A", "b": "B"}, "1) A\n\n2) B")


def test_reordered_json_preserves_event_order():
    import json
    content = json.dumps({"titles": [
        {"id": "b", "title": "나"}, {"id": "a", "title": "가"},
    ]})
    assert _apply_titles(content, {"a": "A", "b": "B"}, "1) A\n\n2) B") == "1) 가\n\n2) 나"


def test_empty_selection_does_not_call_the_model(httpx_mock):
    assert summarize_with_openrouter([], BASE_SUMMARY, "key") == BASE_SUMMARY
    assert httpx_mock.get_requests() == []


def test_permanent_http_error_is_not_retried(httpx_mock):
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, status_code=401)
    assert summarize_with_openrouter(_items(), BASE_SUMMARY, "key") == BASE_SUMMARY
    assert len(httpx_mock.get_requests()) == 1


def test_server_error_on_every_attempt_falls_back(
    httpx_mock: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, status_code=500, is_reusable=True)

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key", max_retries=3)

    assert result == BASE_SUMMARY
    assert len(httpx_mock.get_requests()) == 3
    assert "HTTP 500" in capsys.readouterr().err


def test_transient_error_then_success_is_used(httpx_mock: Any) -> None:
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, status_code=503)
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(_titles()))

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert "12월 31일 세계 시가총액 1위 기업은?" in result
    assert len(httpx_mock.get_requests()) == 2


def test_transport_error_falls_back(httpx_mock: Any, capsys: pytest.CaptureFixture[str]) -> None:
    import httpx

    httpx_mock.add_exception(httpx.ConnectError("boom"), method="POST", url=OPENROUTER_URL)

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key", max_retries=1)

    assert result == BASE_SUMMARY
    assert "ConnectError" in capsys.readouterr().err


def test_malformed_json_falls_back(httpx_mock: Any, capsys: pytest.CaptureFixture[str]) -> None:
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, text="<html>gateway</html>")

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert result == BASE_SUMMARY
    assert "not JSON" in capsys.readouterr().err


def test_missing_choices_falls_back(httpx_mock: Any, capsys: pytest.CaptureFixture[str]) -> None:
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json={"error": "rate limited"})

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert result == BASE_SUMMARY
    assert "no choices" in capsys.readouterr().err


def test_empty_choices_list_falls_back(httpx_mock: Any) -> None:
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json={"choices": []})

    assert summarize_with_openrouter(_items(), BASE_SUMMARY, "key") == BASE_SUMMARY


def test_blank_content_falls_back(httpx_mock: Any, capsys: pytest.CaptureFixture[str]) -> None:
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion("   \n "))

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert result == BASE_SUMMARY
    assert "empty" in capsys.readouterr().err


def test_null_content_falls_back(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        method="POST", url=OPENROUTER_URL, json={"choices": [{"message": {"content": None}}]}
    )

    assert summarize_with_openrouter(_items(), BASE_SUMMARY, "key") == BASE_SUMMARY


def test_unexpected_failure_falls_back(
    httpx_mock: Any, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(_titles()))

    def _boom(*_args) -> bool:
        raise RuntimeError("guard exploded")

    monkeypatch.setattr("polymarket_briefing.ai_summary._apply_titles", _boom)

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert result == BASE_SUMMARY
    assert "unexpected RuntimeError" in capsys.readouterr().err


# --- key loading -------------------------------------------------------------


def test_load_openrouter_key_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    assert load_openrouter_key(keys_path="does-not-exist") == "env-key"


def test_load_openrouter_key_reads_keys_file_alias(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    keys = tmp_path / "keys"
    keys.write_text("# secrets\nopenrouter=file-key\n", encoding="utf-8")

    assert load_openrouter_key(keys_path=str(keys)) == "file-key"


def test_load_openrouter_key_missing_returns_none(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert load_openrouter_key(keys_path=str(tmp_path / "keys")) is None
