from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from src.services.notion_service import (
    ensure_event_page_with_details,
    ensure_fanfic_page,
    ensure_select_option,
    schedule_task_exists,
)

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

    for task in tasks_list:
        try:
            task_name = task["task_name"]
            deadline = task["deadline"]
            schedule_title = f"{event_name}：{task_name}"

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
                continue

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
        except KeyError as exc:
            warning_messages.append(f"タスクデータ不足のためスキップしました: {exc}")
        except Exception as exc:
            warning_messages.append(f"{task.get('task_name', 'Unknown')} の登録に失敗しました: {exc}")
            traceback.print_exc()

    return TaskExecutionResult(
        total_count=len(tasks_list),
        created_count=created_count,
        skipped_duplicate_count=skipped_duplicate_count,
        sync_messages=sync_messages,
        warning_messages=sorted(set(warning_messages)),
        tasks_list=tasks_list,
        fanfic_page_url=fanfic_page_url,
        fanfic_used_existing=fanfic_used_existing,
        created_schedule_page_urls=created_schedule_page_urls,
    )
