from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with _get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS current_context (
                user_id TEXT PRIMARY KEY,
                current_event TEXT,
                updated_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                weekday_hours REAL,
                weekend_hours REAL,
                max_consecutive_days INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        connection.commit()


def get_current_event(user_id: str) -> str | None:
    with _get_connection() as connection:
        row = connection.execute(
            "SELECT current_event FROM current_context WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        return None

    return row["current_event"]


def set_current_event(user_id: str, event_name: str) -> None:
    now = _utc_now_iso()

    with _get_connection() as connection:
        connection.execute(
            """
            INSERT INTO current_context (user_id, current_event, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                current_event = excluded.current_event,
                updated_at = excluded.updated_at
            """,
            (user_id, event_name, now),
        )
        connection.commit()
