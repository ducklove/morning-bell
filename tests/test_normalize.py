from polymarket_briefing.normalize import normalize_event


def test_outcomes_json_string_and_token_mapping():
    event = {
        "id": "e1",
        "slug": "sample-event",
        "title": "Sample Event",
        "markets": [
            {
                "id": "m1",
                "question": "Will it happen?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.42", "0.58"]',
                "clobTokenIds": '["t1", "t2"]',
            }
        ],
    }
    outcomes = normalize_event(event)
    assert len(outcomes) == 2
    assert outcomes[0].outcome == "Yes"
    assert outcomes[0].probability == 0.42
    assert outcomes[0].token_id == "t1"


def test_outcomes_list_and_missing_prices_do_not_crash():
    event = {
        "slug": "multi",
        "title": "Multi",
        "markets": [
            {"id": "m1", "question": "A?", "outcomes": ["A", "B"]},
            {"id": "m2", "question": "C?", "outcomes": ["C"]},
        ],
    }
    outcomes = normalize_event(event)
    assert len(outcomes) == 3
    assert all(item.probability is None for item in outcomes)


def test_url_is_event_url():
    event = {"slug": "abc", "title": "ABC", "markets": [{"question": "Q", "outcomes": ["Yes"]}]}
    assert normalize_event(event)[0].url == "https://polymarket.com/event/abc"
