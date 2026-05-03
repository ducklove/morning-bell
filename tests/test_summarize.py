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
    assert "해설:" in text


def test_summary_respects_max_items():
    items = [
        ScoredOutcome(sample_outcome(), 80, None, ("관심도 점수",)),
        ScoredOutcome(sample_outcome("b"), 70),
    ]
    text = summarize(items, max_items=1)
    assert text.count("링크:") == 1


def test_summary_uses_specific_market_question_and_korean_translation():
    yes = sample_outcome()
    no = NormalizedOutcome(**{**yes.__dict__, "outcome": "No", "probability": 0.67})
    yes = NormalizedOutcome(
        **{
            **yes.__dict__,
            "event_title": "Which company has the best AI model end of May?",
            "market_question": "Will Google have the best AI model at the end of May 2026?",
            "probability": 0.33,
        }
    )
    no = NormalizedOutcome(
        **{
            **no.__dict__,
            "event_title": "Which company has the best AI model end of May?",
            "market_question": "Will Google have the best AI model at the end of May 2026?",
        }
    )
    text = summarize(
        [
            ScoredOutcome(yes, 80, 2.0, ("watchlist",)),
            ScoredOutcome(no, 80, -2.0, ("watchlist",)),
        ],
        max_items=7,
    )
    assert "2026년 5월 말 최고 AI 모델 보유 후보: Google" in text
    assert "예 확률이 24시간 전보다 2.0pp 올랐습니다" in text


def test_summary_groups_multi_market_event_with_market_labels():
    google = sample_outcome()
    anthropic = NormalizedOutcome(
        **{
            **google.__dict__,
            "market_id": "m2",
            "market_question": "Will Anthropic have the best AI model at the end of May 2026?",
            "probability": 0.51,
        }
    )
    google = NormalizedOutcome(
        **{
            **google.__dict__,
            "event_title": "Which company has the best AI model end of May?",
            "market_question": "Will Google have the best AI model at the end of May 2026?",
            "probability": 0.33,
        }
    )
    text = summarize(
        [
            ScoredOutcome(google, 80, 2.0, ("watchlist",)),
            ScoredOutcome(anthropic, 75, 1.0, ("watchlist",)),
        ],
        max_items=7,
    )
    assert text.count("링크:") == 1
    assert "2026년 5월 말 최고 AI 모델 경쟁" in text
    assert "Google 예 33.0%" in text
    assert "Anthropic 예 51.0%" in text


def test_summary_translates_generic_market_question_and_outcome_label():
    question = "Will SpaceX be the largest company in the world by market cap on December 31?"
    outcome = NormalizedOutcome(
        **{
            **sample_outcome().__dict__,
            "event_title": question,
            "market_question": question,
            "outcome": "Yes",
        }
    )
    text = summarize([ScoredOutcome(outcome, 80, 1.0, ("watchlist",))], max_items=7)
    assert "12월 31일 세계 시가총액 1위 후보: SpaceX" in text
    assert "예 55.0%" in text
    assert "예 확률이 24시간 전보다 1.0pp 올랐습니다" in text
    assert "왜 봄: 관심 목록" in text
    assert "Yes" not in text
    assert "watchlist" not in text


def test_summary_translates_hormuz_ship_count_market():
    question = "Will 25-49 ships transit the Strait of Hormuz between April 27-May 3?"
    outcome = NormalizedOutcome(
        **{
            **sample_outcome().__dict__,
            "event_title": "How many ships transit the Strait of Hormuz week of Apr 27",
            "market_question": question,
            "outcome": "Yes",
        }
    )
    text = summarize([ScoredOutcome(outcome, 80, 10.0, ("24h 급변",))], max_items=7)
    assert "25-49척 통항: 4월 27-5월 3" in text
    assert "예 55.0%" in text


def test_summary_translates_sports_versus_title():
    outcome = NormalizedOutcome(
        **{
            **sample_outcome().__dict__,
            "event_title": "76ers vs. Celtics",
            "market_question": "76ers vs. Celtics",
            "outcome": "Celtics",
        }
    )
    text = summarize([ScoredOutcome(outcome, 80, -28.0, ("거래량 큼",))], max_items=7)
    assert "76ers 대 Celtics" in text
