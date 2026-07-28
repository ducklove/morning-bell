from __future__ import annotations

from typing import Any

import pytest

from polymarket_briefing.ai_summary import (
    DISCLAIMER_LINE,
    OPENROUTER_URL,
    _numbers_are_grounded,
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


# --- grounding guard ---------------------------------------------------------


def test_swapped_numbers_between_entities_are_rejected() -> None:
    """The regression test: subset-only checking passes this, pairing must not."""
    swapped = BASE_SUMMARY.replace(
        "Apple 예 79.3% (+1.2pp); NVIDIA 예 20.5% (-1.2pp)",
        "NVIDIA 예 79.3% (+1.2pp); Apple 예 20.5% (-1.2pp)",
    )
    # Every (number, unit) token is still present in the base summary...
    assert sorted(_tokens(swapped)) == sorted(_tokens(BASE_SUMMARY))
    # ...but the numbers now belong to the wrong companies.
    assert _numbers_are_grounded(swapped, BASE_SUMMARY) is False


def test_legitimate_korean_rewording_is_accepted() -> None:
    assert _numbers_are_grounded(CLEAN_AI_TEXT, BASE_SUMMARY) is True


def test_reworded_text_that_drops_an_entity_is_accepted() -> None:
    trimmed = "\n".join(
        [
            "1) 시가총액 1위 경쟁",
            "Apple이 79.3%로 선두를 지키고 있습니다.",
            DISCLAIMER_LINE,
        ]
    )
    assert _numbers_are_grounded(trimmed, BASE_SUMMARY) is True


def test_invented_number_is_rejected() -> None:
    invented = CLEAN_AI_TEXT.replace("79.3%", "88.4%")
    assert _numbers_are_grounded(invented, BASE_SUMMARY) is False


def test_invented_delta_is_rejected() -> None:
    invented = CLEAN_AI_TEXT.replace("(+1.2pp)", "(+9.9pp)")
    assert _numbers_are_grounded(invented, BASE_SUMMARY) is False


def test_swapped_deltas_are_rejected() -> None:
    swapped_delta = CLEAN_AI_TEXT.replace("(+1.2pp)", "(-1.2pp)", 1).replace(
        "20.5% (-1.2pp)", "20.5% (+1.2pp)"
    )
    assert _numbers_are_grounded(swapped_delta, BASE_SUMMARY) is False


def test_reordered_entities_with_intact_pairings_are_accepted() -> None:
    reordered = "\n".join(
        [
            "1) 시가총액 1위 경쟁",
            "NVIDIA 20.5% (-1.2pp), Apple 79.3% (+1.2pp)",
            DISCLAIMER_LINE,
        ]
    )
    assert _numbers_are_grounded(reordered, BASE_SUMMARY) is True


def test_number_borrowed_from_another_item_is_rejected() -> None:
    """Attribution is scoped per item, so numbers cannot drift across items."""
    bled = "\n".join(
        [
            "1) 최고 AI 모델 경쟁",
            "Google 79.3% (+1.2pp)",
            "",
            "2) 시가총액 1위 경쟁",
            "Apple 79.3% (+1.2pp); NVIDIA 20.5% (-1.2pp)",
            DISCLAIMER_LINE,
        ]
    )
    assert _numbers_are_grounded(bled, MULTI_ITEM_BASE) is False


def test_ambiguous_respectively_phrasing_is_rejected() -> None:
    """Known false positive, kept deliberately: ambiguity must fail closed."""
    ambiguous = "\n".join(
        [
            "1) 시가총액 1위 경쟁",
            "Apple과 NVIDIA가 각각 79.3%, 20.5%를 기록했습니다.",
            DISCLAIMER_LINE,
        ]
    )
    assert _numbers_are_grounded(ambiguous, BASE_SUMMARY) is False


def test_subject_named_after_the_number_is_accepted() -> None:
    trailing_subject = "\n".join(
        [
            "1) 시가총액 1위 경쟁",
            "79.3% (+1.2pp)를 기록한 Apple이 선두를 지키고 있습니다.",
            DISCLAIMER_LINE,
        ]
    )
    assert _numbers_are_grounded(trailing_subject, BASE_SUMMARY) is True


def test_subject_missing_from_base_is_only_membership_checked() -> None:
    """Documented gap: a subject the base never names in Latin script cannot be paired."""
    translated_subject = "\n".join(
        [
            "1) 시가총액 1위 경쟁",
            "애플(AAPL) 79.3% (+1.2pp), 엔비디아 20.5% (-1.2pp)",
            DISCLAIMER_LINE,
        ]
    )
    assert _numbers_are_grounded(translated_subject, BASE_SUMMARY) is True


def test_empty_text_is_rejected() -> None:
    assert _numbers_are_grounded("   \n  ", BASE_SUMMARY) is False


def test_text_without_numbers_is_accepted() -> None:
    assert _numbers_are_grounded("오늘은 특별한 움직임이 없습니다.", BASE_SUMMARY) is True


def _tokens(text: str) -> list[tuple[float, str]]:
    from polymarket_briefing.ai_summary import _numeric_tokens

    return list(_numeric_tokens(text))


# --- end-to-end summarization ------------------------------------------------


def test_clean_response_is_returned_with_disclaimer(httpx_mock: Any) -> None:
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(CLEAN_AI_TEXT))

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert result != BASE_SUMMARY
    assert "Apple이 79.3%" in result
    assert result.strip().endswith(DISCLAIMER_LINE)
    assert result.count(DISCLAIMER_LINE) == 1
    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers["Authorization"] == "Bearer key"


def test_missing_disclaimer_is_appended(httpx_mock: Any) -> None:
    without_disclaimer = CLEAN_AI_TEXT.replace(DISCLAIMER_LINE, "").strip()
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(without_disclaimer))

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert result.strip().endswith(DISCLAIMER_LINE)


def test_missing_header_is_restored_from_base(httpx_mock: Any) -> None:
    body = "\n".join(
        [
            "1) 12월 31일 시가총액 1위 경쟁",
            "Apple이 79.3% (+1.2pp)로 앞서고 있습니다.",
            DISCLAIMER_LINE,
        ]
    )
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(body))

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert result.splitlines()[0] == BASE_SUMMARY.splitlines()[0]


def test_swapped_response_falls_back_to_base(
    httpx_mock: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    swapped = CLEAN_AI_TEXT.replace(
        "Apple이 79.3% (+1.2pp)로 앞서고, NVIDIA는 20.5% (-1.2pp)",
        "NVIDIA가 79.3% (+1.2pp)로 앞서고, Apple은 20.5% (-1.2pp)",
    )
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(swapped))

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert result == BASE_SUMMARY
    assert "warning: AI summary unavailable" in capsys.readouterr().err


def test_invented_number_response_falls_back_to_base(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        method="POST",
        url=OPENROUTER_URL,
        json=_completion(CLEAN_AI_TEXT.replace("20.5%", "42.0%")),
    )

    assert summarize_with_openrouter(_items(), BASE_SUMMARY, "key") == BASE_SUMMARY


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
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(CLEAN_AI_TEXT))

    result = summarize_with_openrouter(_items(), BASE_SUMMARY, "key")

    assert "Apple이 79.3%" in result
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
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json=_completion(CLEAN_AI_TEXT))

    def _boom(_ai_text: str, _base: str) -> bool:
        raise RuntimeError("guard exploded")

    monkeypatch.setattr("polymarket_briefing.ai_summary._numbers_are_grounded", _boom)

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
