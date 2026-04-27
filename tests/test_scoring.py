from datetime import UTC, datetime, timedelta

import pytest

from polymarket_briefing.config import AppConfig
from polymarket_briefing.models import NormalizedOutcome
from polymarket_briefing.scoring import (
    change_signal,
    deadline_signal,
    log_signal,
    probability_signal,
    relevance_signal,
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
