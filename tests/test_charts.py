from datetime import UTC, datetime

from polymarket_briefing.charts import _history_points


def test_history_points_keeps_zero_price_and_timestamp():
    history = {"history": [{"t": 0, "p": 0.0}, {"t": 100, "p": 0.5}]}

    points = _history_points(history)

    assert points == [
        (datetime.fromtimestamp(0, tz=UTC), 0.0),
        (datetime.fromtimestamp(100, tz=UTC), 0.5),
    ]


def test_history_points_are_utc_aware():
    history = {"history": [{"t": 1700000000, "p": 0.3}]}

    (point_time, _price) = _history_points(history)[0]

    assert point_time.tzinfo is UTC


def test_history_points_ignores_malformed_entries():
    history = {"history": [{"t": None, "p": 0.5}, "not-a-dict", {"p": 0.5}]}

    assert _history_points(history) == []
