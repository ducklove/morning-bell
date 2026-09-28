from datetime import UTC, datetime, timedelta

from polymarket_briefing.cli import (
    _briefing_dedupe_key,
    _collapse_similar_events,
    _filter_closed,
    _filter_discovery,
    _hide_no_hope_outcomes,
    _limit_by_event_count,
    _reference_probability,
    _select_items,
    _topic_signature,
    _with_stale_watchlist_notice,
)
from polymarket_briefing.models import NormalizedOutcome, ReasonCode, ScoredOutcome


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
    scored = [ScoredOutcome(outcome(), 20, 1.0, (ReasonCode.RECENTLY_SENT, ReasonCode.WATCHLIST))]

    assert _select_items(scored, {"watch"}, min_score=35) == []


def test_recently_sent_watchlist_item_with_sharp_change_can_be_reselected():
    reasons = (ReasonCode.RECENTLY_SENT, ReasonCode.WATCHLIST, ReasonCode.SHARP_CHANGE)
    item = ScoredOutcome(outcome(), 20, 5.0, reasons)

    assert _select_items([item], {"watch"}, min_score=35) == [item]


def test_recently_sent_event_below_threshold_is_not_reselected():
    reasons = (ReasonCode.EVENT_RECENTLY_SENT, ReasonCode.WATCHLIST)
    scored = [ScoredOutcome(outcome(), 30, 1.0, reasons)]

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
    assert "[점검] 워치리스트 1개가 종료됨 · 목록 갱신 필요" in result


def test_stale_watchlist_notice_is_absent_when_watchlist_is_healthy():
    message = "1) 항목\n꼬리표: 정보 요약이며 투자 조언이 아닙니다."

    assert _with_stale_watchlist_notice(message, []) == message


def test_topic_signature_ignores_settlement_date():
    july = _topic_signature("Largest Company end of July?")
    august = _topic_signature("Largest Company end of August?")
    december = _topic_signature("Largest Company end of December 2026?")

    assert july == august == december


def test_topic_signature_keeps_genuinely_different_questions_apart():
    assert _topic_signature("Largest Company end of July?") != _topic_signature(
        "Next round of US-Iran peace talks by July 31?"
    )


def test_collapse_similar_events_keeps_only_the_first_event_per_topic():
    july = ScoredOutcome(outcome("largest-july", event_title="Largest Company end of July?"), 90)
    august = ScoredOutcome(
        outcome("largest-august", event_title="Largest Company end of August?"), 80
    )
    other = ScoredOutcome(outcome("hormuz", event_title="Strait of Hormuz normal?"), 70)

    collapsed = _collapse_similar_events([july, august, other], max_events_per_topic=1)

    assert collapsed == [july, other]


def test_collapse_similar_events_keeps_every_outcome_of_a_kept_event():
    yes = ScoredOutcome(outcome("a", event_title="Largest Company end of July?"), 90)
    no = ScoredOutcome(
        outcome("a", outcome="No", event_title="Largest Company end of July?"), 89
    )

    assert _collapse_similar_events([yes, no], max_events_per_topic=1) == [yes, no]


def test_hide_no_hope_outcomes_drops_hopeless_candidates():
    lead = ScoredOutcome(outcome("e", market_id="m1", probability=0.62), 90)
    hopeless = ScoredOutcome(outcome("e", market_id="m2", probability=0.001), 40)

    assert _hide_no_hope_outcomes([lead, hopeless], 0.03) == [lead]


def test_hide_no_hope_outcomes_never_empties_an_event():
    only = ScoredOutcome(outcome("e", probability=0.001), 40)

    assert _hide_no_hope_outcomes([only], 0.03) == [only]


def test_briefing_dedupe_key_reacts_to_a_change_below_the_top_item():
    now = datetime(2026, 7, 28, tzinfo=UTC)
    top = ScoredOutcome(outcome("a", probability=0.5), 90)
    second = ScoredOutcome(outcome("b", probability=0.4), 80)
    moved = ScoredOutcome(outcome("b", probability=0.9), 80)

    assert _briefing_dedupe_key(now, [top, second]) != _briefing_dedupe_key(now, [top, moved])
    assert _briefing_dedupe_key(now, [top, second]) == _briefing_dedupe_key(now, [top, second])


def test_briefing_dedupe_key_is_stable_for_an_empty_briefing():
    now = datetime(2026, 7, 28, tzinfo=UTC)

    assert _briefing_dedupe_key(now, []) == _briefing_dedupe_key(now, [])
