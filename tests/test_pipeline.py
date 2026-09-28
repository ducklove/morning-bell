from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from typer.testing import CliRunner

from polymarket_briefing.cli import app

NOW = datetime(2026, 9, 29, tzinfo=UTC)
GAMMA = "https://gamma-test.example"
NTFY = "https://ntfy.sh/test-topic"


def event(slug="openai", title=None, probability=0.5, volume_24h=1000, closed=False):
    market = {
        "id": slug + "-market", "question": title or "Will OpenAI release a new model?",
        "outcomes": ["Yes", "No"], "outcomePrices": [probability, 1 - probability],
        "volume": 1_000_000, "volume24hr": volume_24h, "liquidity": 1000,
        "closed": closed, "active": True,
    }
    return {"id": slug, "slug": slug, "title": title or slug, "markets": [market]}


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    monkeypatch.setattr("polymarket_briefing.cli.utc_now", lambda: NOW)
    monkeypatch.setattr("polymarket_briefing.notifier.time.sleep", lambda _: None)
    raw = {
        "polymarket": {"gamma_base_url": GAMMA, "max_retries": 0, "backoff_seconds": 0},
        "discovery": {"max_events": 20, "min_volume_24h": 1000},
        "scoring": {"min_score_to_notify": 0},
        "storage": {"path": str(tmp_path / "state.sqlite")},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def update_config(path, **sections):
    raw = yaml.safe_load(path.read_text())
    for key, value in sections.items():
        if isinstance(value, dict):
            raw.setdefault(key, {}).update(value)
        else:
            raw[key] = value
    path.write_text(yaml.safe_dump(raw))


def run(path, *, dry=True):
    args = ["run", "--config", str(path)]
    if dry:
        args.append("--dry-run")
    return CliRunner().invoke(app, args)


def discovery(httpx_mock, events, **kwargs):
    httpx_mock.add_response(
        method="GET", url=re.compile(GAMMA + r"/events\?"), json=events, **kwargs,
    )


def sent_slugs(path):
    with sqlite3.connect(path.parent / "state.sqlite") as db:
        return {row[0] for row in db.execute("SELECT DISTINCT event_slug FROM sent_outcomes")}


def test_total_api_failure_exits_nonzero_without_sending(config_path, httpx_mock):
    httpx_mock.add_response(method="GET", status_code=451)
    result = run(config_path)
    assert result.exit_code == 1
    assert "모든 데이터 소스 조회에 실패" in result.output
    assert "관심 시장이 없습니다" not in result.output
    assert "종료됨" not in result.output
    assert not (config_path.parent / "state.sqlite").exists()
    assert all(r.method == "GET" for r in httpx_mock.get_requests())


def test_empty_success_is_a_valid_empty_briefing(config_path, httpx_mock):
    discovery(httpx_mock, [])
    result = run(config_path)
    assert result.exit_code == 0
    assert "관심 시장이 없습니다" in result.stdout
    assert "조회 실패" not in result.stdout


@pytest.mark.parametrize("payload", [{}, {"data": "changed"}, [42]])
def test_changed_discovery_schema_is_not_reported_as_no_markets(
    config_path, httpx_mock, payload,
):
    discovery(httpx_mock, payload)
    result = run(config_path)
    assert result.exit_code == 1
    assert "관심 시장이 없습니다" not in result.stdout


def test_partial_failure_and_closed_market_have_distinct_notices(config_path, httpx_mock):
    update_config(config_path, watchlist_slugs=["closed", "unavailable"])
    httpx_mock.add_response(url=GAMMA + "/events/slug/closed", json=event("closed", closed=True))
    httpx_mock.add_response(url=GAMMA + "/events/slug/unavailable", status_code=503)
    httpx_mock.add_response(url=GAMMA + "/events?slug=unavailable", status_code=503)
    discovery(httpx_mock, [event()])
    result = run(config_path)
    assert result.exit_code == 0
    assert "워치리스트 1개가 종료됨" in result.stdout
    assert "데이터 소스 1개 조회 실패" in result.stdout
    assert "https://polymarket.com/event/openai" in result.stdout


def test_configured_pagination_and_filters_reach_http_request(config_path, httpx_mock):
    update_config(
        config_path, polymarket={"page_size": 1},
        discovery={"max_events": 2, "include_active_only": False, "include_closed": True},
    )
    discovery(httpx_mock, [event("one", closed=True)])
    discovery(httpx_mock, [event("two")])
    result = run(config_path)
    assert result.exit_code == 0
    requests = httpx_mock.get_requests()
    assert [r.url.params["offset"] for r in requests] == ["0", "1"]
    assert all(r.url.params["limit"] == "1" for r in requests)
    assert all("active" not in r.url.params and "closed" not in r.url.params for r in requests)
    assert "https://polymarket.com/event/one" in result.stdout


def test_topic_dedupe_precedes_event_limit(config_path, httpx_mock):
    update_config(config_path, scoring={"max_items": 2})
    discovery(httpx_mock, [
        event("july", "Largest Company end of July?"),
        event("august", "Largest Company end of August?"),
        event("other", "OpenAI release date?"),
    ])
    result = run(config_path)
    assert result.exit_code == 0
    assert result.stdout.count("링크:") == 2
    assert "/other" in result.stdout


def test_zero_daily_volume_is_not_replaced_by_total_volume(config_path, httpx_mock):
    discovery(httpx_mock, [event(volume_24h=0)])
    result = run(config_path)
    assert result.exit_code == 0
    assert "관심 시장이 없습니다" in result.stdout


def test_missing_daily_volume_can_use_the_total(config_path, httpx_mock):
    discovery(httpx_mock, [event(volume_24h=None)])
    result = run(config_path)
    assert result.exit_code == 0
    assert "/openai" in result.stdout


def test_sharp_change_on_next_day_can_resend_discovery(
    config_path, httpx_mock, monkeypatch,
):
    update_config(
        config_path,
        discovery={"keywords": {"ai": {"weight": 1, "terms": ["OpenAI"]}}},
        scoring={"min_score_to_notify": 35},
    )
    discovery(httpx_mock, [event(probability=0.5)])
    httpx_mock.add_response(method="POST", url=NTFY)
    assert run(config_path, dry=False).exit_code == 0
    monkeypatch.setattr("polymarket_briefing.cli.utc_now", lambda: NOW + timedelta(days=1))
    discovery(httpx_mock, [event(probability=0.8)])
    httpx_mock.add_response(method="POST", url=NTFY)
    result = run(config_path, dry=False)
    assert result.exit_code == 0
    posts = [r for r in httpx_mock.get_requests() if r.method == "POST"]
    assert len(posts) == 2
    assert "24시간 급변" in posts[-1].content.decode()


def test_failed_delivery_keeps_snapshots_without_a_sent_receipt(config_path, httpx_mock):
    discovery(httpx_mock, [event()])
    httpx_mock.add_response(method="POST", url=NTFY, status_code=503, is_reusable=True)
    result = run(config_path, dry=False)
    assert result.exit_code != 0
    with sqlite3.connect(config_path.parent / "state.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM outcome_snapshots").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM sent_notifications").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sent_outcomes").fetchone()[0] == 0


def test_same_content_is_not_posted_twice(config_path, httpx_mock):
    discovery(httpx_mock, [event()], is_reusable=True)
    httpx_mock.add_response(method="POST", url=NTFY)
    assert run(config_path, dry=False).exit_code == 0
    assert run(config_path, dry=False).exit_code == 0
    assert len([r for r in httpx_mock.get_requests() if r.method == "POST"]) == 1


def test_preview_and_delivery_fit_whole_events_and_record_only_visible_ones(
    config_path, httpx_mock,
):
    update_config(config_path, scoring={"max_events_per_topic": 0})
    discovery(httpx_mock, [
        event(f"e{i}", "한국어 질문 " + "긴설명 " * 60 + str(i)) for i in range(7)
    ], is_reusable=True)
    preview = run(config_path)
    assert preview.exit_code == 0
    assert not (config_path.parent / "state.sqlite").exists()
    httpx_mock.add_response(method="POST", url=NTFY)
    delivered = run(config_path, dry=False)
    assert delivered.exit_code == 0
    body = httpx_mock.get_requests()[-1].content.decode()
    assert body.strip() == preview.stdout.strip()
    assert len(body.encode()) <= 4032
    visible = set(re.findall(r"https://polymarket.com/event/(e\d+)", body))
    assert 0 < len(visible) < 7
    assert sent_slugs(config_path) == visible
    assert body.strip().endswith("꼬리표: 정보 요약이며 투자 조언이 아닙니다.")


def test_hidden_no_outcomes_are_not_recorded_as_displayed(config_path, httpx_mock):
    payload = event()
    payload["markets"].append(event("second", "Will Google win?")["markets"][0])
    discovery(httpx_mock, [payload])
    httpx_mock.add_response(method="POST", url=NTFY)
    assert run(config_path, dry=False).exit_code == 0
    with sqlite3.connect(config_path.parent / "state.sqlite") as db:
        assert db.execute("SELECT outcome FROM sent_outcomes").fetchall() == [("Yes",), ("Yes",)]


def test_validation_command_does_not_access_network_or_create_state(config_path, httpx_mock):
    result = CliRunner().invoke(app, ["validate-config", "--config", str(config_path)])
    assert result.exit_code == 0
    assert httpx_mock.get_requests() == []
    assert not (config_path.parent / "state.sqlite").exists()


def test_ai_response_cannot_drop_facts_in_the_full_pipeline(config_path, httpx_mock, monkeypatch):
    from polymarket_briefing.ai_summary import OPENROUTER_URL

    update_config(config_path, ai_summary={"enabled": True})
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    discovery(httpx_mock, [event()])
    httpx_mock.add_response(method="POST", url=OPENROUTER_URL, json={
        "choices": [{"message": {"content": json.dumps({
            "titles": [{"id": "openai", "title": "OpenAI의 새 모델 공개 여부"}],
        })}}],
    })
    result = run(config_path)
    assert result.exit_code == 0
    assert "OpenAI의 새 모델 공개 여부" in result.stdout
    assert "예 50.0%; 아니오 50.0%" in result.stdout
    assert "/openai" in result.stdout

