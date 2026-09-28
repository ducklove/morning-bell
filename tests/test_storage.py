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


def test_snapshot_lookup_matches_market_id_including_null(tmp_path):
    now = datetime.now(UTC)
    yesterday = now - timedelta(hours=24)
    with BriefingStorage(str(tmp_path / "state.sqlite")) as storage:
        storage.insert_snapshots(
            [
                sample_outcome(0.10, market_id="m1"),
                sample_outcome(0.20, market_id="m2"),
                sample_outcome(0.30, market_id=None),
            ],
            yesterday,
        )

        non_null = storage.find_snapshot_around(sample_outcome(0.5, market_id="m1"), now)
        assert non_null is not None
        assert non_null.market_id == "m1"
        assert non_null.probability == 0.10

        null_id = storage.find_snapshot_around(sample_outcome(0.5, market_id=None), now)
        assert null_id is not None
        assert null_id.market_id is None
        assert null_id.probability == 0.30

        # a market_id with no stored row must not fall back to the NULL row
        assert storage.find_snapshot_around(sample_outcome(0.5, market_id="missing"), now) is None


def test_snapshot_lookup_uses_index(tmp_path):
    now = datetime.now(UTC)
    with BriefingStorage(str(tmp_path / "state.sqlite")) as storage:
        storage.insert_snapshots([sample_outcome(0.4)], now - timedelta(hours=24))
        captured = []
        storage.connection.set_trace_callback(captured.append)
        storage.find_snapshot_around(sample_outcome(0.5), now)
        storage.connection.set_trace_callback(None)
        sql = next(item for item in captured if "outcome_snapshots" in item)
        plan = [
            row[-1] for row in storage.connection.execute("EXPLAIN QUERY PLAN " + sql).fetchall()
        ]
        assert any("idx_outcome_snapshots_lookup" in step for step in plan), plan


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


def test_legacy_state_is_copied_outside_checkout_only_once(tmp_path, monkeypatch):
    from polymarket_briefing.storage import LEGACY_STORAGE_PATH

    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "external-state"
    monkeypatch.setenv("POLYMARKET_BRIEFING_STATE_DIR", str(state_dir))
    legacy = tmp_path / LEGACY_STORAGE_PATH
    with BriefingStorage(str(legacy)) as storage:
        storage.record_notification("old", "title", datetime.now(UTC))
    with BriefingStorage(LEGACY_STORAGE_PATH) as migrated:
        assert migrated.path == state_dir / "briefing_state.sqlite"
        assert migrated.notification_sent("old")
        migrated.record_notification("new", "title", datetime.now(UTC))
    with BriefingStorage(str(legacy)) as original:
        assert not original.notification_sent("new")
        original.record_notification("stale-copy", "title", datetime.now(UTC))
    with BriefingStorage(LEGACY_STORAGE_PATH) as reopened:
        assert reopened.notification_sent("new")
        assert not reopened.notification_sent("stale-copy")


def test_dry_run_reads_legacy_without_migrating_or_writing(tmp_path, monkeypatch):
    from polymarket_briefing.storage import DEFAULT_STORAGE_PATH, LEGACY_STORAGE_PATH

    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "external-state"
    monkeypatch.setenv("POLYMARKET_BRIEFING_STATE_DIR", str(state_dir))
    legacy = tmp_path / LEGACY_STORAGE_PATH
    with BriefingStorage(str(legacy)) as storage:
        storage.record_notification("old", "title", datetime.now(UTC))
    before = legacy.read_bytes()
    with BriefingStorage(DEFAULT_STORAGE_PATH, read_only=True) as preview:
        assert preview.notification_sent("old")
        preview.record_notification("preview", "title", datetime.now(UTC))
    assert legacy.read_bytes() == before
    assert not state_dir.exists()


def test_backup_is_consistent_and_cannot_overwrite_existing_file(tmp_path):
    path = tmp_path / "state.sqlite"
    backup = tmp_path / "backups" / "before-deploy.sqlite"
    with BriefingStorage(str(path)) as storage:
        storage.record_notification("receipt", "title", datetime.now(UTC))
        storage.backup_to(backup)
        with pytest.raises(FileExistsError):
            storage.backup_to(backup)
    with BriefingStorage(str(backup)) as copied:
        assert copied.notification_sent("receipt")
        assert copied.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_delivery_receipt_is_atomic_on_duplicate_key(tmp_path):
    import sqlite3

    with BriefingStorage(str(tmp_path / "state.sqlite")) as storage:
        now = datetime.now(UTC)
        storage.record_delivery("same", "title", [sample_outcome()], now)
        with pytest.raises(sqlite3.IntegrityError):
            storage.record_delivery("same", "title", [sample_outcome(market_id="other")], now)
        assert storage.recently_sent_outcome_keys(now, 7) == {("slug", "m1", "Yes")}
