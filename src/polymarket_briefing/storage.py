from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polymarket_briefing.models import NormalizedOutcome, Snapshot


class BriefingStorage:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> BriefingStorage:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS outcome_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              observed_at TEXT NOT NULL,
              event_slug TEXT NOT NULL,
              market_id TEXT,
              market_question TEXT NOT NULL,
              outcome TEXT NOT NULL,
              probability REAL,
              volume REAL,
              volume_24h REAL,
              liquidity REAL,
              url TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sent_notifications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              sent_at TEXT NOT NULL,
              dedupe_key TEXT NOT NULL UNIQUE,
              title TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sent_outcomes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              sent_at TEXT NOT NULL,
              event_slug TEXT NOT NULL,
              market_id TEXT,
              outcome TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sent_outcomes_recent
              ON sent_outcomes (sent_at, event_slug, market_id, outcome);
            """
        )
        self.connection.commit()

    def insert_snapshots(self, outcomes: list[NormalizedOutcome], observed_at: datetime) -> None:
        self.connection.executemany(
            """
            INSERT INTO outcome_snapshots (
              observed_at, event_slug, market_id, market_question, outcome,
              probability, volume, volume_24h, liquidity, url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    observed_at.isoformat(),
                    item.event_slug,
                    item.market_id,
                    item.market_question,
                    item.outcome,
                    item.probability,
                    item.volume,
                    item.volume_24h,
                    item.liquidity,
                    item.url,
                )
                for item in outcomes
            ],
        )
        self.connection.commit()

    def find_snapshot_around(
        self, outcome: NormalizedOutcome, observed_at: datetime, hours_back: int = 24
    ) -> Snapshot | None:
        target = observed_at - timedelta(hours=hours_back)
        lower = target - timedelta(hours=6)
        upper = target + timedelta(hours=6)
        rows = self.connection.execute(
            """
            SELECT * FROM outcome_snapshots
            WHERE observed_at BETWEEN ? AND ?
              AND event_slug = ?
              AND COALESCE(market_id, '') = COALESCE(?, '')
              AND market_question = ?
              AND outcome = ?
            ORDER BY ABS(strftime('%s', observed_at) - strftime('%s', ?))
            LIMIT 1
            """,
            (
                lower.isoformat(),
                upper.isoformat(),
                outcome.event_slug,
                outcome.market_id,
                outcome.market_question,
                outcome.outcome,
                target.isoformat(),
            ),
        ).fetchone()
        return _row_to_snapshot(rows) if rows else None

    def notification_sent(self, dedupe_key: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sent_notifications WHERE dedupe_key = ?", (dedupe_key,)
        ).fetchone()
        return row is not None

    def record_notification(self, dedupe_key: str, title: str, sent_at: datetime) -> bool:
        try:
            self.connection.execute(
                "INSERT INTO sent_notifications (sent_at, dedupe_key, title) VALUES (?, ?, ?)",
                (sent_at.isoformat(), dedupe_key, title),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def recently_sent_outcome_keys(
        self, observed_at: datetime, days_back: int
    ) -> set[tuple[str, str | None, str]]:
        cutoff = observed_at - timedelta(days=max(days_back, 0))
        rows = self.connection.execute(
            """
            SELECT DISTINCT event_slug, market_id, outcome
            FROM sent_outcomes
            WHERE sent_at >= ?
            """,
            (cutoff.isoformat(),),
        ).fetchall()
        return {(row["event_slug"], row["market_id"], row["outcome"]) for row in rows}

    def record_sent_outcomes(
        self, outcomes: list[NormalizedOutcome], sent_at: datetime
    ) -> None:
        self.connection.executemany(
            """
            INSERT INTO sent_outcomes (sent_at, event_slug, market_id, outcome)
            VALUES (?, ?, ?, ?)
            """,
            [
                (sent_at.isoformat(), item.event_slug, item.market_id, item.outcome)
                for item in outcomes
            ],
        )
        self.connection.commit()


def calculate_snapshot_delta_pp(
    storage: BriefingStorage, outcome: NormalizedOutcome, observed_at: datetime
) -> float | None:
    previous = storage.find_snapshot_around(outcome, observed_at)
    if previous is None or previous.probability is None or outcome.probability is None:
        return None
    return (outcome.probability - previous.probability) * 100


def dedupe_key_for(
    date: datetime,
    item_slug: str,
    market_id: str | None,
    outcome: str,
    probability: float | None,
    delta: float | None,
) -> str:
    return ":".join(
        [
            date.astimezone(UTC).date().isoformat(),
            item_slug,
            market_id or "",
            outcome,
            str(round(probability or 0, 3)),
            str(round(delta or 0, 1)),
        ]
    )


def _row_to_snapshot(row: sqlite3.Row) -> Snapshot:
    return Snapshot(
        observed_at=datetime.fromisoformat(row["observed_at"]),
        event_slug=row["event_slug"],
        market_id=row["market_id"],
        market_question=row["market_question"],
        outcome=row["outcome"],
        probability=row["probability"],
        volume=row["volume"],
        volume_24h=row["volume_24h"],
        liquidity=row["liquidity"],
        url=row["url"],
    )
