from polymarket_briefing.models import NormalizedOutcome, ScoredOutcome
from polymarket_briefing.summarize import summarize


def sample_outcome(event_slug="slug"):
    return NormalizedOutcome(
        event_id=None,
        event_slug=event_slug,
        event_title="Title",
        market_id="m1",
        market_slug=None,
        market_question="Question",
        outcome="Yes",
        probability=0.55,
        token_id=None,
        volume=1,
        volume_24h=1,
        liquidity=1,
        end_date=None,
        active=True,
        closed=False,
        resolution_source=None,
        url=f"https://polymarket.com/event/{event_slug}",
    )


def test_summary_contains_korean_header_url_and_disclaimer():
    item = ScoredOutcome(sample_outcome(), 80, 6.5, ("watchlist",))
    text = summarize([item], max_items=7)
    assert "Polymarket 아침 브리핑" in text
    assert "https://polymarket.com/event/slug" in text
    assert "정보 요약이며 투자 조언이 아닙니다" in text
    assert "(+6.5pp)" in text


def test_summary_respects_max_items():
    items = [
        ScoredOutcome(sample_outcome(), 80, None, ("관심도 점수",)),
        ScoredOutcome(sample_outcome("b"), 70),
    ]
    text = summarize(items, max_items=1)
    assert text.count("링크:") == 1
