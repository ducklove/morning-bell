from datetime import UTC, datetime, timedelta

from polymarket_briefing.cli import (
    _filter_closed,
    _filter_discovery,
    _limit_by_event_count,
    _reference_probability,
    _select_items,
    _with_stale_watchlist_notice,
)
from polymarket_briefing.models import NormalizedOutcome, ScoredOutcome


def outcome(event_slug="watch", **kwargs):
    defaults = dict(
        event_id=None,
        event_slug=event_slug,
        event_title="Title",
        market_id="m1",
        market_slug=None,
        market_question="Question",
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
        url=f"https://polymarket.com/event/{event_slug}",
    )
    defaults.update(kwargs)
    return NormalizedOutcome(
        **defaults,
    )


def test_recently_sent_watchlist_item_below_threshold_is_not_reselected():
    scored = [ScoredOutcome(outcome(), 20, 1.0, ("최근 발송", "watchlist"))]

    assert _select_items(scored, {"watch"}, min_score=35) == []


def test_recently_sent_watchlist_item_with_sharp_change_can_be_reselected():
    item = ScoredOutcome(outcome(), 20, 5.0, ("최근 발송", "watchlist", "24h 급변"))

    assert _select_items([item], {"watch"}, min_score=35) == [item]


def test_recently_sent_event_below_threshold_is_not_reselected():
    scored = [ScoredOutcome(outcome(), 30, 1.0, ("최근 이벤트", "watchlist"))]

    assert _select_items(scored, {"watch"}, min_score=35) == []


def test_filter_discovery_excludes_noisy_interest_terms():
    item = outcome(
        event_slug="trump-say",
        event_title="What will Trump say during bilateral events?",
        market_question='Will Trump say "Iran"?',
        volume_24h=1000,
    )

    assert _filter_discovery([item], 1000, ["what will trump say"]) == []


def test_limit_by_event_count_keeps_whole_events():
    yes_a = ScoredOutcome(outcome("a", outcome="Yes"), 80)
    no_a = ScoredOutcome(outcome("a", outcome="No"), 79)
    yes_b = ScoredOutcome(outcome("b", outcome="Yes"), 70)
    no_b = ScoredOutcome(outcome("b", outcome="No"), 69)

    limited = _limit_by_event_count([yes_a, no_a, yes_b, no_b], max_events=1)

    assert limited == [yes_a, no_a]


def test_limit_by_event_count_under_limit_is_unchanged():
    items = [ScoredOutcome(outcome("a"), 80), ScoredOutcome(outcome("b"), 70)]

    assert _limit_by_event_count(items, max_events=5) == items


def test_filter_closed_drops_resolved_watchlist_markets():
    open_item = outcome("watch", closed=False)
    closed_item = outcome("watch", market_id="m2", closed=True)

    assert _filter_closed([open_item, closed_item]) == [open_item]


def test_reference_probability_picks_point_nearest_target():
    target = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)
    points = [
        (target - timedelta(hours=2), 0.10),
        (target + timedelta(minutes=5), 0.42),
        (target + timedelta(hours=2), 0.90),
    ]

    assert _reference_probability(points, target) == 0.42


def test_reference_probability_rejects_points_outside_tolerance():
    target = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)
    far = [(target - timedelta(hours=12), 0.42)]

    assert _reference_probability(far, target) is None
    assert _reference_probability([], target) is None


def test_stale_watchlist_notice_sits_above_disclaimer():
    message = "1) 항목\n링크: https://x\n\n꼬리표: 정보 요약이며 투자 조언이 아닙니다."

    result = _with_stale_watchlist_notice(message, ["dead-slug"])
    lines = result.splitlines()

    assert lines[-1].startswith("꼬리표:")
    assert "[점검] 워치리스트 1개가 종료됨: dead-slug" in result


def test_stale_watchlist_notice_is_absent_when_watchlist_is_healthy():
    message = "1) 항목\n꼬리표: 정보 요약이며 투자 조언이 아닙니다."

    assert _with_stale_watchlist_notice(message, []) == message
