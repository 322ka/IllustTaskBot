from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from src.services.estimate_runtime_service import get_work_type_weight
from src.services.google_calendar_service import DAY_CAPACITY_HOURS, build_daily_blocked_hours, list_events, summarize_events
from src.services.notion_service import (
    ensure_event_page_with_details,
    ensure_fanfic_page,
    ensure_select_option,
    list_schedule_entries_for_event,
    list_schedule_entries_on_date,
    schedule_task_exists,
    update_schedule_entry_date,
)
from src.services.progress_service import list_estimate_snapshots, list_progress_records

WORKFLOW_STEPS = [
    "情報収集",
    "イメージ策定",
    "大ラフ",
    "詳細ラフ",
    "カラーラフ",
    "下書き",
    "線画",
    "色分け",
    "着彩",
    "修正",
    "仕上げ",
]

WORKFLOW_STEP_BASE_HOURS = {
    "情報収集": 1.0,
    "イメージ策定": 1.5,
    "大ラフ": 2.0,
    "詳細ラフ": 2.0,
    "カラーラフ": 2.0,
    "下書き": 2.0,
    "線画": 3.0,
    "色分け": 2.0,
    "着彩": 3.0,
    "修正": 1.5,
    "仕上げ": 2.0,
}

DEFAULT_TASK_HOURS = 3.0
NORMAL_DAY_CAPACITY_HOURS = 8.0
LIGHT_DAY_CAPACITY_HOURS = 5.0
SEMI_ALL_DAY_CAPACITY_HOURS = 2.0
ALL_DAY_CAPACITY_HOURS = 0.0


@dataclass
class TaskExecutionResult:
    total_count: int
    created_count: int
    skipped_duplicate_count: int
    sync_messages: list[str]
    warning_messages: list[str]
    tasks_list: list[dict[str, str]]
    fanfic_page_url: str | None = None
    fanfic_used_existing: bool = False
    created_schedule_page_urls: list[str] | None = None
    auto_shifted_count: int = 0


@dataclass
class RescheduleExecutionResult:
    target_count: int
    moved_count: int
    unchanged_count: int
    sync_messages: list[str]
    warning_messages: list[str]
    moved_page_urls: list[str]


TASK_JSON_EXAMPLE = """[
  {
    \"step\": 1,
    \"task_name\": \"情報収集\",
    \"deadline\": \"YYYY-MM-DD\",
    \"description\": \"クライアント依頼内容や参考情報の整理\"
  }
]"""


def build_task_generation_prompt(
    *,
    work_title: str,
    due_date: str,
    work_category: str,
    work_type: str,
) -> str:
    workflow_text = "\n".join(f"{index}. {step}" for index, step in enumerate(WORKFLOW_STEPS, start=1))
    return f"""あなたはイラストレーターの制作管理アシスタントです。
以下の作品情報から、締切日までに間に合うよう各工程の締切日を逆算してください。

作品名: {work_title}
最終締切: {due_date}
作業種別: {work_category}
作品種別: {work_type}

標準工程:
{workflow_text}

要件:
- 最終工程「仕上げ」の deadline が {due_date} になるようにしてください
- 各工程は現実的に 1-2 日ずつ余裕を見て配置してください
- 工程数は上記 11 工程を維持してください
- 説明文やコードブロックは不要です
- JSON 配列のみを返してください

出力形式:
{TASK_JSON_EXAMPLE}
"""


def generate_task_plan(
    *,
    openai_client: Any,
    work_title: str,
    due_date: str,
    work_category: str,
    work_type: str,
) -> list[dict[str, str]]:
    prompt = build_task_generation_prompt(
        work_title=work_title,
        due_date=due_date,
        work_category=work_category,
        work_type=work_type,
    )
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    response_text = response.choices[0].message.content
    print(f"task.ai raw response repr: {response_text!r}")

    if not response_text or not response_text.strip():
        raise ValueError("AI の応答が空でした。")

    cleaned_response_text = response_text.strip()
    if "```json" in cleaned_response_text:
        cleaned_response_text = cleaned_response_text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in cleaned_response_text:
        cleaned_response_text = cleaned_response_text.split("```", 1)[1].split("```", 1)[0].strip()

    print(f"task.ai cleaned response preview: {cleaned_response_text[:300]!r}")
    tasks_list = json.loads(cleaned_response_text)
    if not isinstance(tasks_list, list):
        raise ValueError("AI の応答形式が不正です。")
    return tasks_list


def _extract_step_name_from_schedule_title(title: str) -> str:
    if "｜" in title:
        return title.split("｜")[-1].strip()
    if "：" in title:
        return title.split("：")[-1].strip()
    if ":" in title:
        return title.split(":")[-1].strip()
    return title.strip()


def execute_task_registration(
    *,
    notion: Any,
    notion_db_id: str,
    event_database_id: str | None,
    fanfic_database_id: str | None,
    tasks_list: list[dict[str, str]],
    work_title: str,
    work_category: str,
    work_type: str,
    event_name: str,
    user_id: str | None = None,
    get_database_schema_config: Callable[[str], tuple[str, dict[str, set[str]]]],
    build_select_property: Callable[[str, str | None, dict[str, set[str]], list[str]], dict | None],
    notion_prop_schedule_date: str,
    notion_prop_category: str,
    notion_prop_event: str,
    notion_prop_work_title: str,
    notion_prop_done: str,
) -> TaskExecutionResult:
    title_property_name, select_options = get_database_schema_config(notion_db_id)
    warning_messages: list[str] = []
    sync_messages: list[str] = []
    fanfic_page_url: str | None = None
    fanfic_used_existing = False
    created_schedule_page_urls: list[str] = []

    try:
        work_title_sync_result = ensure_select_option(
            notion=notion,
            database_id=notion_db_id,
            property_name=notion_prop_work_title,
            option_name=work_title,
        )
        select_options.setdefault(notion_prop_work_title, set()).add(work_title)
        if work_title_sync_result == "added":
            sync_messages.append("SCHEDULE同期: 作品タイトル候補を追加しました。")
    except Exception as exc:
        warning_messages.append(f"{notion_prop_work_title}: '{work_title}' を設定できないためスキップ ({exc})")

    try:
        event_sync_result = ensure_select_option(
            notion=notion,
            database_id=notion_db_id,
            property_name=notion_prop_event,
            option_name=event_name,
        )
        select_options.setdefault(notion_prop_event, set()).add(event_name)
        if event_sync_result == "added":
            sync_messages.append("SCHEDULE同期: イベント候補を追加しました。")
    except Exception as exc:
        warning_messages.append(f"{notion_prop_event}: '{event_name}' を設定できないためスキップ ({exc})")

    if event_database_id:
        try:
            event_page_result, event_title_property_name = ensure_event_page_with_details(
                notion=notion,
                database_id=event_database_id,
                event_name=event_name,
            )
            if event_page_result == "created":
                sync_messages.append(
                    f"EVENT同期: イベントページを作成しました。 (title: {event_title_property_name})"
                )
            else:
                sync_messages.append(
                    f"EVENT同期: 既存のイベントページを利用しました。 (title: {event_title_property_name})"
                )
        except Exception as exc:
            warning_messages.append(f"EVENT同期に失敗しました: {exc}")
    else:
        sync_messages.append("EVENT同期: NOTION_EVENT_DATABASE_ID が未設定のためスキップしました。")

    if fanfic_database_id:
        try:
            fanfic_event_sync_result = ensure_select_option(
                notion=notion,
                database_id=fanfic_database_id,
                property_name="イベント",
                option_name=event_name,
            )
            if fanfic_event_sync_result == "added":
                sync_messages.append("FANFIC同期: イベント候補を追加しました。")

            fanfic_category_sync_result = ensure_select_option(
                notion=notion,
                database_id=fanfic_database_id,
                property_name="分類タグ",
                option_name=work_type,
            )
            if fanfic_category_sync_result == "added":
                sync_messages.append("FANFIC同期: 分類タグ候補を追加しました。")

            fanfic_result, fanfic_title_property_name, fanfic_warnings, fanfic_page_url = ensure_fanfic_page(
                notion=notion,
                database_id=fanfic_database_id,
                work_title=work_title,
                event_name=event_name,
                category_name=work_type,
                status_name="未着手",
            )
            fanfic_used_existing = fanfic_result == "exists"
            if fanfic_result == "created":
                sync_messages.append(
                    f"FANFIC同期: 作品ページを作成しました。 (title: {fanfic_title_property_name})"
                )
            else:
                sync_messages.append(
                    f"FANFIC同期: 既存の作品ページを利用しました。 (title: {fanfic_title_property_name})"
                )
            warning_messages.extend(fanfic_warnings)
        except Exception as exc:
            warning_messages.append(f"FANFIC同期に失敗しました: {exc}")
    else:
        sync_messages.append("FANFIC同期: NOTION_FANFIC_DATABASE_ID が未設定のためスキップしました。")

    created_count = 0
    skipped_duplicate_count = 0
    auto_shifted_count = 0
    updated_tasks_list: list[dict[str, str]] = []
    schedule_load_cache: dict[str, float] = {}
    snapshot_hours_map: dict[tuple[str, str, str], float] = {}
    progress_hours_map: dict[tuple[str, str, str], float] = {}

    if user_id:
        try:
            for snapshot in list_estimate_snapshots(user_id=user_id, event_name=event_name):
                snapshot_hours_map[(snapshot.event_name, snapshot.work_title, snapshot.step_name)] = snapshot.estimated_hours
            for record in list_progress_records(user_id=user_id, event_name=event_name):
                progress_hours_map[(record.event_name, record.work_title, record.step_name)] = record.actual_hours
        except Exception as exc:
            warning_messages.append(f"実績参照に失敗しました: {exc}")

    parsed_deadlines = [
        datetime.strptime(task["deadline"], "%Y-%m-%d").date()
        for task in tasks_list
        if task.get("deadline")
    ]
    calendar_summary = None
    calendar_error = None
    calendar_events: list[Any] = []
    if parsed_deadlines:
        calendar_events, calendar_error = list_events(
            calendar_id=None,
            time_min=datetime.combine(min(parsed_deadlines) - timedelta(days=30), datetime.min.time()),
            time_max=datetime.combine(max(parsed_deadlines), datetime.max.time()),
            max_results=200,
        )
        if calendar_error:
            warning_messages.append(f"Googleカレンダー参照に失敗しました: {calendar_error}")
        else:
            calendar_summary = summarize_events(calendar_events)
    blocked_hours_map = build_daily_blocked_hours(calendar_events) if calendar_events else {}

    def get_day_capacity_hours(date_value: str) -> float:
        blocked_hours = blocked_hours_map.get(date_value, 0.0)
        return max(DAY_CAPACITY_HOURS - blocked_hours, 0.0)

    def estimate_task_hours(step_name: str, *, weighted: bool) -> float:
        base_hours = WORKFLOW_STEP_BASE_HOURS.get(step_name, DEFAULT_TASK_HOURS)
        if weighted:
            return round(base_hours * get_work_type_weight(work_type), 2)
        return base_hours

    def estimate_existing_schedule_entry_hours(*, entry_title: str, entry_work_title: str) -> float:
        step_name = _extract_step_name_from_schedule_title(entry_title)
        progress_key = (event_name, entry_work_title, step_name)
        if progress_key in progress_hours_map:
            return progress_hours_map[progress_key]
        snapshot_key = (event_name, entry_work_title, step_name)
        if snapshot_key in snapshot_hours_map:
            return snapshot_hours_map[snapshot_key]
        return estimate_task_hours(step_name, weighted=False)

    def get_existing_schedule_load(date_value: str) -> float:
        if date_value in schedule_load_cache:
            return schedule_load_cache[date_value]

        entries = list_schedule_entries_on_date(
            notion=notion,
            database_id=notion_db_id,
            title_property_name=title_property_name,
            work_title_property_name=notion_prop_work_title,
            date_property_name=notion_prop_schedule_date,
            date_value=date_value,
        )
        load_hours = 0.0
        for entry in entries:
            load_hours += estimate_existing_schedule_entry_hours(
                entry_title=entry["title"],
                entry_work_title=entry["work_title"],
            )

        schedule_load_cache[date_value] = round(load_hours, 2)
        return schedule_load_cache[date_value]

    def resolve_schedule_deadline(original_deadline: str, task_name: str) -> str:
        nonlocal auto_shifted_count
        candidate_date = datetime.strptime(original_deadline, "%Y-%m-%d").date()
        earliest_allowed_date = datetime.now().date()
        if candidate_date < earliest_allowed_date:
            candidate_date = earliest_allowed_date
        task_hours = estimate_task_hours(task_name, weighted=True)

        while candidate_date >= earliest_allowed_date:
            candidate_key = candidate_date.isoformat()
            existing_load = get_existing_schedule_load(candidate_key)
            if existing_load + task_hours <= get_day_capacity_hours(candidate_key):
                schedule_load_cache[candidate_key] = round(existing_load + task_hours, 2)
                if candidate_key != original_deadline:
                    auto_shifted_count += 1
                return candidate_key
            candidate_date -= timedelta(days=1)

        fallback_key = earliest_allowed_date.isoformat()
        fallback_load = get_existing_schedule_load(fallback_key)
        schedule_load_cache[fallback_key] = round(fallback_load + task_hours, 2)
        if fallback_key != original_deadline:
            auto_shifted_count += 1
        return fallback_key

    for task in tasks_list:
        try:
            task_name = task["task_name"]
            schedule_title = f"{event_name}｜{work_title}｜{task_name}"

            if schedule_task_exists(
                notion=notion,
                database_id=notion_db_id,
                title_property_name=title_property_name,
                title_value=schedule_title,
                work_title_property_name=notion_prop_work_title,
                work_title_value=work_title,
                event_property_name=notion_prop_event,
                event_value=event_name,
            ):
                skipped_duplicate_count += 1
                updated_tasks_list.append(dict(task))
                continue

            deadline = resolve_schedule_deadline(task["deadline"], task_name)
            updated_task = dict(task)
            updated_task["deadline"] = deadline

            properties = {
                title_property_name: {"title": [{"text": {"content": schedule_title}}]},
                notion_prop_schedule_date: {"date": {"start": deadline}},
                notion_prop_done: {"checkbox": False},
            }

            category_prop = build_select_property(
                notion_prop_category,
                work_category,
                select_options,
                warning_messages,
            )
            if category_prop:
                properties[notion_prop_category] = category_prop

            work_title_prop = build_select_property(
                notion_prop_work_title,
                work_title,
                select_options,
                warning_messages,
            )
            if work_title_prop:
                properties[notion_prop_work_title] = work_title_prop

            event_prop = build_select_property(
                notion_prop_event,
                event_name,
                select_options,
                warning_messages,
            )
            if event_prop:
                properties[notion_prop_event] = event_prop

            created_page = notion.pages.create(
                parent={"database_id": notion_db_id},
                properties=properties,
            )
            if created_page.get("url"):
                created_schedule_page_urls.append(created_page["url"])
            created_count += 1
            updated_tasks_list.append(updated_task)
        except KeyError as exc:
            warning_messages.append(f"タスクデータ不足のためスキップしました: {exc}")
        except Exception as exc:
            warning_messages.append(f"{task.get('task_name', 'Unknown')} の登録に失敗しました: {exc}")
            traceback.print_exc()

    if auto_shifted_count:
        sync_messages.append(
            f"SCHEDULE同期: 作業時間と予定圧を考慮して {auto_shifted_count} 件の締切を前倒し調整しました。"
        )

    return TaskExecutionResult(
        total_count=len(tasks_list),
        created_count=created_count,
        skipped_duplicate_count=skipped_duplicate_count,
        sync_messages=sync_messages,
        warning_messages=sorted(set(warning_messages)),
        tasks_list=updated_tasks_list or tasks_list,
        fanfic_page_url=fanfic_page_url,
        fanfic_used_existing=fanfic_used_existing,
        created_schedule_page_urls=created_schedule_page_urls,
        auto_shifted_count=auto_shifted_count,
    )


def execute_schedule_reschedule(
    *,
    notion: Any,
    notion_db_id: str,
    event_name: str,
    user_id: str | None,
    get_database_schema_config: Callable[[str], tuple[str, dict[str, set[str]]]],
    notion_prop_schedule_date: str,
    notion_prop_event: str,
    notion_prop_work_title: str,
    notion_prop_done: str,
) -> RescheduleExecutionResult:
    title_property_name, _ = get_database_schema_config(notion_db_id)
    warning_messages: list[str] = []
    sync_messages: list[str] = []
    moved_page_urls: list[str] = []
    schedule_load_cache: dict[str, float] = {}
    snapshot_hours_map: dict[tuple[str, str, str], float] = {}
    progress_hours_map: dict[tuple[str, str, str], float] = {}

    if user_id:
        try:
            for snapshot in list_estimate_snapshots(user_id=user_id, event_name=event_name):
                snapshot_hours_map[(snapshot.event_name, snapshot.work_title, snapshot.step_name)] = snapshot.estimated_hours
            for record in list_progress_records(user_id=user_id, event_name=event_name):
                progress_hours_map[(record.event_name, record.work_title, record.step_name)] = record.actual_hours
        except Exception as exc:
            warning_messages.append(f"実績参照に失敗しました: {exc}")

    entries = list_schedule_entries_for_event(
        notion=notion,
        database_id=notion_db_id,
        title_property_name=title_property_name,
        work_title_property_name=notion_prop_work_title,
        event_property_name=notion_prop_event,
        date_property_name=notion_prop_schedule_date,
        done_property_name=notion_prop_done,
        event_value=event_name,
        include_done=False,
    )
    if not entries:
        return RescheduleExecutionResult(
            target_count=0,
            moved_count=0,
            unchanged_count=0,
            sync_messages=["再調整対象の未完了タスクはありません。"],
            warning_messages=[],
            moved_page_urls=[],
        )

    target_ids = {str(entry["id"]) for entry in entries}
    target_entries = sorted(
        entries,
        key=lambda entry: (str(entry["date"]), str(entry["title"])),
    )

    parsed_dates = [
        datetime.strptime(str(entry["date"])[:10], "%Y-%m-%d").date()
        for entry in target_entries
    ]
    calendar_events: list[Any] = []
    calendar_error = None
    if parsed_dates:
        calendar_events, calendar_error = list_events(
            calendar_id=None,
            time_min=datetime.combine(datetime.now().date(), datetime.min.time()),
            time_max=datetime.combine(max(parsed_dates), datetime.max.time()),
            max_results=200,
        )
        if calendar_error:
            warning_messages.append(f"Googleカレンダー参照に失敗しました: {calendar_error}")
    blocked_hours_map = build_daily_blocked_hours(calendar_events) if calendar_events else {}

    def get_day_capacity_hours(date_value: str) -> float:
        blocked_hours = blocked_hours_map.get(date_value, 0.0)
        return max(DAY_CAPACITY_HOURS - blocked_hours, 0.0)

    def estimate_entry_hours(*, entry_title: str, entry_work_title: str) -> float:
        step_name = _extract_step_name_from_schedule_title(entry_title)
        progress_key = (event_name, entry_work_title, step_name)
        if progress_key in progress_hours_map:
            return progress_hours_map[progress_key]
        snapshot_key = (event_name, entry_work_title, step_name)
        if snapshot_key in snapshot_hours_map:
            return snapshot_hours_map[snapshot_key]
        return WORKFLOW_STEP_BASE_HOURS.get(step_name, DEFAULT_TASK_HOURS)

    def get_existing_schedule_load(date_value: str) -> float:
        if date_value in schedule_load_cache:
            return schedule_load_cache[date_value]

        same_day_entries = list_schedule_entries_on_date(
            notion=notion,
            database_id=notion_db_id,
            title_property_name=title_property_name,
            work_title_property_name=notion_prop_work_title,
            date_property_name=notion_prop_schedule_date,
            date_value=date_value,
        )
        load_hours = 0.0
        for entry in same_day_entries:
            if str(entry.get("id", "")) in target_ids:
                continue
            load_hours += estimate_entry_hours(
                entry_title=str(entry["title"]),
                entry_work_title=str(entry["work_title"]),
            )
        schedule_load_cache[date_value] = round(load_hours, 2)
        return schedule_load_cache[date_value]

    moved_count = 0
    unchanged_count = 0
    today = datetime.now().date()

    for entry in target_entries:
        original_date = datetime.strptime(str(entry["date"])[:10], "%Y-%m-%d").date()
        candidate_date = max(today, original_date)
        task_hours = estimate_entry_hours(
            entry_title=str(entry["title"]),
            entry_work_title=str(entry["work_title"]),
        )

        assigned_key: str | None = None
        for _ in range(90):
            candidate_key = candidate_date.isoformat()
            existing_load = get_existing_schedule_load(candidate_key)
            if existing_load + task_hours <= get_day_capacity_hours(candidate_key):
                schedule_load_cache[candidate_key] = round(existing_load + task_hours, 2)
                assigned_key = candidate_key
                break
            candidate_date += timedelta(days=1)

        if assigned_key is None:
            assigned_key = candidate_date.isoformat()

        if assigned_key != original_date.isoformat():
            update_schedule_entry_date(
                notion=notion,
                page_id=str(entry["id"]),
                date_property_name=notion_prop_schedule_date,
                date_value=assigned_key,
            )
            moved_count += 1
            if entry.get("url"):
                moved_page_urls.append(str(entry["url"]))
        else:
            unchanged_count += 1

    if moved_count:
        sync_messages.append(f"再調整: {moved_count} 件のタスク日付を再配置しました。")
    if unchanged_count:
        sync_messages.append(f"再調整: {unchanged_count} 件はそのまま維持しました。")

    return RescheduleExecutionResult(
        target_count=len(target_entries),
        moved_count=moved_count,
        unchanged_count=unchanged_count,
        sync_messages=sync_messages,
        warning_messages=warning_messages,
        moved_page_urls=moved_page_urls,
    )
