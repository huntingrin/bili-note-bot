"""SQLite persistence: per-BV dedupe, card path, send status, failures, daily quota."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    bv          TEXT PRIMARY KEY,
    mid         INTEGER,
    uname       TEXT,
    title       TEXT,
    up_name     TEXT,
    duration    INTEGER,
    card_path   TEXT,
    status      TEXT NOT NULL DEFAULT 'new',
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    sent_at     TEXT
);

CREATE TABLE IF NOT EXISTS at_seen (
    item_id     TEXT PRIMARY KEY,
    bv          TEXT,
    mid         INTEGER,
    seen_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS failures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bv          TEXT,
    mid         INTEGER,
    stage       TEXT,
    code        INTEGER,
    message     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quota (
    day         TEXT PRIMARY KEY,
    sent        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS contacts (
    mid          INTEGER PRIMARY KEY,
    last_sent_at TEXT NOT NULL,
    sends        INTEGER NOT NULL DEFAULT 1
);
"""

STATUS_CARDED = "carded"
STATUS_SENT = "sent"
STATUS_DRYRUN = "dryrun"
STATUS_FAILED = "failed"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- videos ---------------------------------------------------------
    def get_video(self, bv: str) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM videos WHERE bv = ?", (bv,)).fetchone()

    def has_card(self, bv: str) -> bool:
        row = self.get_video(bv)
        if not row or row["status"] not in (STATUS_CARDED, STATUS_SENT, STATUS_DRYRUN):
            return False
        card = row["card_path"]
        return bool(card) and Path(card).is_file()

    def upsert_video(self, bv: str, **fields) -> None:
        now = _now()
        cols = {k: v for k, v in fields.items() if v is not None}
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO videos (bv, created_at, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(bv) DO NOTHING",
                (bv, now, now),
            )
            if cols:
                assignments = ", ".join(f"{k} = ?" for k in cols)
                conn.execute(
                    f"UPDATE videos SET {assignments}, updated_at = ? WHERE bv = ?",
                    (*cols.values(), now, bv),
                )

    def set_status(self, bv: str, status: str, error: str | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE videos SET status = ?, error = ?, updated_at = ?, "
                "sent_at = CASE WHEN ? = ? THEN ? ELSE sent_at END WHERE bv = ?",
                (status, error, _now(), status, STATUS_SENT, _now(), bv),
            )

    # ---- at feed dedupe -------------------------------------------------
    def seen_at_item(self, item_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM at_seen WHERE item_id = ?", (item_id,)).fetchone()
            return row is not None

    def mark_at_item(self, item_id: str, bv: str | None, mid: int | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO at_seen (item_id, bv, mid, seen_at) VALUES (?, ?, ?, ?)",
                (item_id, bv, mid, _now()),
            )

    # ---- failures -------------------------------------------------------
    def add_failure(self, bv: str | None, mid: int | None, stage: str, message: str,
                    code: int | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO failures (bv, mid, stage, code, message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (bv, mid, stage, code, message[:2000], _now()),
            )

    def recent_failures(self, limit: int = 10) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM failures ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    # ---- quota ----------------------------------------------------------
    def sent_today(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT sent FROM quota WHERE day = ?", (date.today().isoformat(),)
            ).fetchone()
            return int(row["sent"]) if row else 0

    def incr_sent_today(self) -> int:
        day = date.today().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO quota (day, sent) VALUES (?, 1) "
                "ON CONFLICT(day) DO UPDATE SET sent = sent + 1",
                (day,),
            )
            row = conn.execute("SELECT sent FROM quota WHERE day = ?", (day,)).fetchone()
            return int(row["sent"])

    # ---- contacts (21047 mitigation) ------------------------------------
    def has_contact(self, mid: int) -> bool:
        if not mid:
            return False
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM contacts WHERE mid = ?", (mid,)).fetchone()
            return row is not None

    def touch_contact(self, mid: int) -> None:
        if not mid:
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO contacts (mid, last_sent_at, sends) VALUES (?, ?, 1) "
                "ON CONFLICT(mid) DO UPDATE SET last_sent_at = excluded.last_sent_at, "
                "sends = sends + 1",
                (mid, _now()),
            )
