from datetime import UTC, datetime, timedelta

import pytest

from polymarket_briefing.models import NormalizedOutcome
from polymarket_briefing.storage import BriefingStorage, calculate_snapshot_delta_pp


def sample_outcome(probability=0.55, **kwargs):
    defaults = dict(
        event_id=None,
        event_slug="slug",
        event_title="Title",
        market_id="m1",
        market_slug=None,
        market_question="Question",
        outcome="Yes",
        probability=probability,
        token_id=None,
        volume=1,
        volume_24h=1,
        liquidity=1,
        end_date=None,
        active=True,
        closed=False,
        resolution_source=None,
        url="https://polymarket.com/event/slug",
    )
    defaults.update(kwargs)
    return NormalizedOutcome(
        **defaults,
    )


def test_snapshot_insert_and_lookup(tmp_path):
    now = datetime.now(UTC)
    with BriefingStorage(str(tmp_path / "state.sqlite")) as storage:
        storage.insert_snapshots([sample_outcome(0.4)], now - timedelta(hours=24))
        previous = storage.find_snapshot_around(sample_outcome(0.5), now)
        assert previous is not None
        assert previous.probability == 0.4
        assert calculate_snapshot_delta_pp(storage, sample_outcome(0.5), now) == pytest.approx(10.0)


def test_notification_dedupe(tmp_path):
    now = datetime.now(UTC)
    with BriefingStorage(str(tmp_path / "state.sqlite")) as storage:
        assert storage.record_notification("key", "title", now) is True
        assert storage.record_notification("key", "title", now) is False
        assert storage.notification_sent("key") is True


def test_recently_sent_outcome_keys_respect_window(tmp_path):
    now = datetime.now(UTC)
    with BriefingStorage(str(tmp_path / "state.sqlite")) as storage:
        storage.record_sent_outcomes([sample_outcome()], now - timedelta(days=2))
        storage.record_sent_outcomes(
            [sample_outcome(market_id="old")], now - timedelta(days=10)
        )

        assert storage.recently_sent_outcome_keys(now, days_back=7) == {("slug", "m1", "Yes")}


def test_prune_older_than_removes_stale_rows_only(tmp_path):
    now = datetime.now(UTC)
    with BriefingStorage(str(tmp_path / "state.sqlite")) as storage:
        storage.insert_snapshots([sample_outcome()], now - timedelta(days=40))
        storage.insert_snapshots([sample_outcome()], now - timedelta(days=1))
        storage.record_sent_outcomes([sample_outcome(market_id="old")], now - timedelta(days=40))
        storage.record_sent_outcomes([sample_outcome(market_id="recent")], now - timedelta(days=1))
        storage.record_notification("stale-key", "title", now - timedelta(days=40))
        storage.record_notification("recent-key", "title", now - timedelta(days=1))

        storage.prune_older_than(now - timedelta(days=30))

        remaining_snapshots = storage.connection.execute(
            "SELECT COUNT(*) FROM outcome_snapshots"
        ).fetchone()[0]
        remaining_sent = storage.recently_sent_outcome_keys(now, days_back=365)
        assert remaining_snapshots == 1
        assert remaining_sent == {("slug", "recent", "Yes")}
        assert storage.notification_sent("stale-key") is False
        assert storage.notification_sent("recent-key") is True
