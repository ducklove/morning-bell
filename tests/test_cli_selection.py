from polymarket_briefing.cli import _filter_discovery, _select_items
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
