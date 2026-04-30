from datetime import UTC, datetime, timedelta

import pytest

from polymarket_briefing.config import AppConfig, ScoringSettings
from polymarket_briefing.models import NormalizedOutcome
from polymarket_briefing.scoring import (
    _contains_term,
    change_signal,
    deadline_signal,
    log_signal,
    probability_signal,
    relevance_signal,
    score_outcome,
)


def outcome(**kwargs):
    defaults = dict(
        event_id=None,
        event_slug="watch",
        event_title="OpenAI model market",
        market_id="m1",
        market_slug=None,
        market_question="Will OpenAI win?",
        outcome="Yes",
        probability=0.5,
        token_id=None,
        volume=100,
        volume_24h=50,
        liquidity=10,
        end_date=None,
        active=True,
        closed=False,
        resolution_source=None,
        url="https://polymarket.com/event/watch",
    )
    defaults.update(kwargs)
    return NormalizedOutcome(**defaults)


def test_watchlist_relevance_default():
    cfg = AppConfig(watchlist_slugs=["watch"])
    assert relevance_signal(outcome(), cfg) >= 0.8


def test_ten_pp_change_caps_at_one():
    assert change_signal(10.0) == 1.0
    assert change_signal(15.0) == 1.0


def test_deadline_within_seven_days():
    now = datetime.now(UTC)
    assert deadline_signal(outcome(end_date=now + timedelta(days=2)), now) == 1.0


def test_log_signal_bounds():
    assert 0 <= log_signal(10, 100) <= 1
    assert log_signal(1000, 100) == 1


def test_probability_signal_penalizes_extremes():
    assert probability_signal(0.5) == 1.0
    assert probability_signal(0.9) == pytest.approx(0.2)
    assert probability_signal(0.99) == pytest.approx(0.02)


def test_keyword_matching_uses_term_boundaries():
    assert _contains_term("gpt-5.6 released by july", "GPT-5.6")
    assert _contains_term("spacex ipo closing market cap", "IPO")
    assert not _contains_term("orlando magic win series", "AGI")


def test_recently_sent_outcome_is_heavily_penalized():
    now = datetime.now(UTC)
    cfg = AppConfig(
        watchlist_slugs=["watch"],
        scoring=ScoringSettings(sent_penalty_factor=0.2),
    )
    original = score_outcome(outcome(), 10.0, cfg, now, 50, 10)
    penalized = score_outcome(outcome(), 10.0, cfg, now, 50, 10, already_sent=True)

    assert penalized.score == pytest.approx(original.score * 0.2)
    assert "최근 발송" in penalized.reasons


def test_recently_sent_event_is_penalized_less_than_exact_outcome():
    now = datetime.now(UTC)
    cfg = AppConfig(
        watchlist_slugs=["watch"],
        scoring=ScoringSettings(sent_penalty_factor=0.2, sent_event_penalty_factor=0.6),
    )
    original = score_outcome(outcome(outcome="No"), 10.0, cfg, now, 50, 10)
    penalized = score_outcome(
        outcome(outcome="No"),
        10.0,
        cfg,
        now,
        50,
        10,
        event_recently_sent=True,
    )
    exact = score_outcome(
        outcome(outcome="No"),
        10.0,
        cfg,
        now,
        50,
        10,
        already_sent=True,
        event_recently_sent=True,
    )

    assert penalized.score == pytest.approx(original.score * 0.6)
    assert "최근 이벤트" in penalized.reasons
    assert exact.score == pytest.approx(original.score * 0.2)
    assert "최근 이벤트" not in exact.reasons
