from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone

from src.models.estimate_runtime_definitions import EstimateStep
from src.services.db_service import DB_PATH, DATA_DIR


PROGRESS_STATUS_NOT_STARTED = "未着手"
PROGRESS_STATUS_IN_PROGRESS = "進行中"
PROGRESS_STATUS_DONE = "完了"


@dataclass
class EstimateSnapshotRecord:
    user_id: str
    event_name: str
    work_title: str
    due_date: str
    work_category: str
    work_type: str
    step_name: str
    step_order: int
    estimated_hours: float
    estimate_created_at: str


@dataclass
class ProgressRecord:
    user_id: str
    event_name: str
    work_title: str
    step_name: str
    estimated_hours: float | None
    actual_hours: float
    progress_status: str
    memo: str | None
    updated_at: str


@dataclass
class WorkProgressSummary:
    event_name: str
    work_title: str
    due_date: str
    work_category: str
    work_type: str
    estimated_total_hours: float
    actual_total_hours: float
    variance_hours: float
    total_steps: int
    completed_steps: int
    incomplete_steps: int
    next_steps: list[str]
    latest_status: str
    danger_score: int
    danger_label: str
    days_until_due: int


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def save_estimate_snapshot(
    *,
    user_id: str,
    event_name: str,
    work_title: str,
    due_date: str,
    work_category: str,
    work_type: str,
    steps: list[EstimateStep],
    estimate_created_at: str,
) -> None:
    with _get_connection() as connection:
        connection.execute(
            """
            DELETE FROM estimate_step_snapshots
            WHERE user_id = ? AND event_name = ? AND work_title = ?
            """,
            (user_id, event_name, work_title),
        )
        connection.executemany(
            """
            INSERT INTO estimate_step_snapshots (
                user_id,
                event_name,
                work_title,
                due_date,
                work_category,
                work_type,
                step_name,
                step_order,
                estimated_hours,
                estimate_created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    user_id,
                    event_name,
                    work_title,
                    due_date,
                    work_category,
                    work_type,
                    step["step_name"],
                    index,
                    float(step["hours"]),
                    estimate_created_at,
                )
                for index, step in enumerate(steps, start=1)
            ],
        )
        connection.commit()


def get_estimated_hours(
    *,
    user_id: str,
    event_name: str,
    work_title: str,
    step_name: str,
) -> float | None:
    with _get_connection() as connection:
        row = connection.execute(
            """
            SELECT estimated_hours
            FROM estimate_step_snapshots
            WHERE user_id = ? AND event_name = ? AND work_title = ? AND step_name = ?
            """,
            (user_id, event_name, work_title, step_name),
        ).fetchone()

    if row is None:
        return None
    return float(row["estimated_hours"])


def save_progress_record(
    *,
    user_id: str,
    event_name: str,
    work_title: str,
    step_name: str,
    estimated_hours: float | None,
    actual_hours: float,
    progress_status: str,
    memo: str | None,
) -> str:
    updated_at = _utc_now_iso()
    with _get_connection() as connection:
        connection.execute(
            """
            INSERT INTO progress_records (
                user_id,
                event_name,
                work_title,
                step_name,
                estimated_hours,
                actual_hours,
                progress_status,
                memo,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, event_name, work_title, step_name) DO UPDATE SET
                estimated_hours = excluded.estimated_hours,
                actual_hours = excluded.actual_hours,
                progress_status = excluded.progress_status,
                memo = excluded.memo,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                event_name,
                work_title,
                step_name,
                estimated_hours,
                actual_hours,
                progress_status,
                memo,
                updated_at,
            ),
        )
        connection.commit()
    return updated_at


def list_progress_records(
    *,
    user_id: str,
    event_name: str | None = None,
) -> list[ProgressRecord]:
    query = """
        SELECT
            user_id,
            event_name,
            work_title,
            step_name,
            estimated_hours,
            actual_hours,
            progress_status,
            memo,
            updated_at
        FROM progress_records
        WHERE user_id = ?
    """
    params: list[object] = [user_id]
    if event_name:
        query += " AND event_name = ?"
        params.append(event_name)
    query += " ORDER BY updated_at DESC"

    with _get_connection() as connection:
        rows = connection.execute(query, params).fetchall()

    return [
        ProgressRecord(
            user_id=row["user_id"],
            event_name=row["event_name"],
            work_title=row["work_title"],
            step_name=row["step_name"],
            estimated_hours=float(row["estimated_hours"]) if row["estimated_hours"] is not None else None,
            actual_hours=float(row["actual_hours"]),
            progress_status=row["progress_status"],
            memo=row["memo"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def list_estimate_snapshots(
    *,
    user_id: str,
    event_name: str | None = None,
) -> list[EstimateSnapshotRecord]:
    query = """
        SELECT
            user_id,
            event_name,
            work_title,
            due_date,
            work_category,
            work_type,
            step_name,
            step_order,
            estimated_hours,
            estimate_created_at
        FROM estimate_step_snapshots
        WHERE user_id = ?
    """
    params: list[object] = [user_id]
    if event_name:
        query += " AND event_name = ?"
        params.append(event_name)
    query += " ORDER BY due_date ASC, work_title ASC, step_order ASC"

    with _get_connection() as connection:
        rows = connection.execute(query, params).fetchall()

    return [
        EstimateSnapshotRecord(
            user_id=row["user_id"],
            event_name=row["event_name"],
            work_title=row["work_title"],
            due_date=row["due_date"],
            work_category=row["work_category"],
            work_type=row["work_type"],
            step_name=row["step_name"],
            step_order=int(row["step_order"]),
            estimated_hours=float(row["estimated_hours"]),
            estimate_created_at=row["estimate_created_at"],
        )
        for row in rows
    ]


def build_progress_feedback(*, variance_hours: float | None, status: str) -> str:
    if variance_hours is None:
        return "見積との比較はまだできません。"
    if status == PROGRESS_STATUS_DONE and variance_hours <= -1:
        return "前倒しで進められています。"
    if variance_hours >= 5:
        return "見積よりかなり時間がかかっています。"
    if variance_hours >= 2:
        return "少し遅れています。"
    if variance_hours <= -1:
        return "予定より早めに進んでいます。"
    return "おおむね予定通りです。"


def _danger_label_from_score(score: int) -> str:
    if score >= 5:
        return "危険度高"
    if score >= 3:
        return "少し遅れ"
    return "順調"


def build_work_progress_summaries(
    *,
    user_id: str,
    event_name: str | None = None,
    today: date | None = None,
) -> list[WorkProgressSummary]:
    snapshots = list_estimate_snapshots(user_id=user_id, event_name=event_name)
    progress_records = list_progress_records(user_id=user_id, event_name=event_name)
    base_date = today or datetime.now().date()

    snapshot_groups: dict[tuple[str, str], list[EstimateSnapshotRecord]] = {}
    for snapshot in snapshots:
        snapshot_groups.setdefault((snapshot.event_name, snapshot.work_title), []).append(snapshot)

    progress_map: dict[tuple[str, str, str], ProgressRecord] = {}
    for record in progress_records:
        progress_map[(record.event_name, record.work_title, record.step_name)] = record

    summaries: list[WorkProgressSummary] = []
    for (group_event_name, group_work_title), rows in snapshot_groups.items():
        ordered_rows = sorted(rows, key=lambda row: row.step_order)
        estimated_total_hours = sum(row.estimated_hours for row in ordered_rows)
        actual_total_hours = 0.0
        tracked_estimated_hours = 0.0
        completed_steps = 0
        next_steps: list[str] = []
        latest_status = PROGRESS_STATUS_NOT_STARTED
        tracked_step_count = 0

        for row in ordered_rows:
            record = progress_map.get((group_event_name, group_work_title, row.step_name))
            if record:
                actual_total_hours += record.actual_hours
                tracked_estimated_hours += row.estimated_hours
                tracked_step_count += 1
                latest_status = record.progress_status
                if record.progress_status == PROGRESS_STATUS_DONE:
                    completed_steps += 1
                elif len(next_steps) < 3:
                    next_steps.append(row.step_name)
            elif len(next_steps) < 3:
                next_steps.append(row.step_name)

        total_steps = len(ordered_rows)
        incomplete_steps = total_steps - completed_steps
        due_date = date.fromisoformat(ordered_rows[0].due_date)
        days_until_due = (due_date - base_date).days
        variance_hours = actual_total_hours - tracked_estimated_hours if tracked_step_count else 0.0

        danger_score = 0
        if days_until_due <= 3:
            danger_score += 3
        elif days_until_due <= 7:
            danger_score += 2
        elif days_until_due <= 14:
            danger_score += 1

        if incomplete_steps >= 3:
            danger_score += 1
        if incomplete_steps >= 5:
            danger_score += 1

        if variance_hours >= 3:
            danger_score += 1
        if variance_hours >= 6:
            danger_score += 1

        summaries.append(
            WorkProgressSummary(
                event_name=group_event_name,
                work_title=group_work_title,
                due_date=ordered_rows[0].due_date,
                work_category=ordered_rows[0].work_category,
                work_type=ordered_rows[0].work_type,
                estimated_total_hours=round(estimated_total_hours, 2),
                actual_total_hours=round(actual_total_hours, 2),
                variance_hours=round(variance_hours, 2),
                total_steps=total_steps,
                completed_steps=completed_steps,
                incomplete_steps=incomplete_steps,
                next_steps=next_steps,
                latest_status=latest_status,
                danger_score=danger_score,
                danger_label=_danger_label_from_score(danger_score),
                days_until_due=days_until_due,
            )
        )

    return sorted(
        summaries,
        key=lambda summary: (-summary.danger_score, summary.days_until_due, summary.work_title),
    )


def build_reschedule_suggestions(
    *,
    user_id: str,
    event_name: str | None = None,
    today: date | None = None,
) -> dict[str, list[str]]:
    summaries = build_work_progress_summaries(user_id=user_id, event_name=event_name, today=today)
    if not summaries:
        return {
            "priority_lines": [],
            "delay_lines": [],
            "focus_lines": [],
        }

    priority_lines = [
        f"{summary.work_title}（{summary.danger_label} / 締切まであと{summary.days_until_due}日）"
        for summary in summaries[:3]
    ]

    delay_lines = [
        f"{summary.work_title}（締切まであと{summary.days_until_due}日 / 未完了{summary.incomplete_steps}工程）"
        for summary in summaries
        if summary.days_until_due >= 14 and summary.danger_score <= 2
    ][:3]

    focus_lines: list[str] = []
    for summary in summaries[:3]:
        if summary.next_steps:
            focus_lines.append(f"{summary.work_title}: {', '.join(summary.next_steps[:2])}")

    return {
        "priority_lines": priority_lines,
        "delay_lines": delay_lines,
        "focus_lines": focus_lines,
    }
