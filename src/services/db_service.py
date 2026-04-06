from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"


ESTIMATE_EXPIRY_SECONDS = 60 * 60 * 6


@dataclass
class LatestEstimateRecord:
    user_id: str
    event_name: str
    work_title: str
    due_date: str
    work_category: str
    work_type: str
    estimate_created_at: str
    task_created_at: str | None = None


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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS latest_estimates (
                user_id TEXT PRIMARY KEY,
                event_name TEXT NOT NULL,
                work_title TEXT NOT NULL,
                due_date TEXT NOT NULL,
                work_category TEXT NOT NULL,
                work_type TEXT NOT NULL,
                estimate_created_at TEXT NOT NULL,
                task_created_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS estimate_step_snapshots (
                user_id TEXT NOT NULL,
                event_name TEXT NOT NULL,
                work_title TEXT NOT NULL,
                due_date TEXT NOT NULL,
                work_category TEXT NOT NULL,
                work_type TEXT NOT NULL,
                step_name TEXT NOT NULL,
                step_order INTEGER NOT NULL,
                estimated_hours REAL NOT NULL,
                estimate_created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, event_name, work_title, step_name)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS progress_records (
                user_id TEXT NOT NULL,
                event_name TEXT NOT NULL,
                work_title TEXT NOT NULL,
                step_name TEXT NOT NULL,
                estimated_hours REAL,
                actual_hours REAL NOT NULL,
                progress_status TEXT NOT NULL,
                memo TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, event_name, work_title, step_name)
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


def save_latest_estimate(
    *,
    user_id: str,
    event_name: str,
    work_title: str,
    due_date: str,
    work_category: str,
    work_type: str,
) -> str:
    now = _utc_now_iso()

    with _get_connection() as connection:
        connection.execute(
            """
            INSERT INTO latest_estimates (
                user_id,
                event_name,
                work_title,
                due_date,
                work_category,
                work_type,
                estimate_created_at,
                task_created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(user_id) DO UPDATE SET
                event_name = excluded.event_name,
                work_title = excluded.work_title,
                due_date = excluded.due_date,
                work_category = excluded.work_category,
                work_type = excluded.work_type,
                estimate_created_at = excluded.estimate_created_at,
                task_created_at = NULL
            """,
            (user_id, event_name, work_title, due_date, work_category, work_type, now),
        )
        connection.commit()

    return now


def get_latest_estimate(user_id: str) -> LatestEstimateRecord | None:
    with _get_connection() as connection:
        row = connection.execute(
            """
            SELECT
                user_id,
                event_name,
                work_title,
                due_date,
                work_category,
                work_type,
                estimate_created_at,
                task_created_at
            FROM latest_estimates
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    if row is None:
        return None

    return LatestEstimateRecord(
        user_id=row["user_id"],
        event_name=row["event_name"],
        work_title=row["work_title"],
        due_date=row["due_date"],
        work_category=row["work_category"],
        work_type=row["work_type"],
        estimate_created_at=row["estimate_created_at"],
        task_created_at=row["task_created_at"],
    )


def mark_latest_estimate_task_created(user_id: str) -> None:
    now = _utc_now_iso()

    with _get_connection() as connection:
        connection.execute(
            """
            UPDATE latest_estimates
            SET task_created_at = ?
            WHERE user_id = ?
            """,
            (now, user_id),
        )
        connection.commit()
