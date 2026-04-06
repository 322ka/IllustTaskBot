from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable

import discord
from discord import app_commands
from discord.ext import commands

from src.services.db_service import get_current_event
from src.services.task_runtime_service import execute_task_registration, generate_task_plan


EVENT_REQUIRED_MESSAGE = (
    "イベント名が指定されていません。先に /event で設定するか、"
    "/task に event_name を指定してください。"
)

WORK_CATEGORY_CHOICES = [
    app_commands.Choice(name="FA", value="FA"),
    app_commands.Choice(name="イベント準備", value="イベント準備"),
    app_commands.Choice(name="依頼", value="依頼"),
    app_commands.Choice(name="その他", value="その他"),
]

WORK_TYPE_CHOICES = [
    app_commands.Choice(name="グッズ", value="グッズ"),
    app_commands.Choice(name="同人誌", value="同人誌"),
    app_commands.Choice(name="ノベルティ", value="ノベルティ"),
    app_commands.Choice(name="ディスプレイ", value="ディスプレイ"),
    app_commands.Choice(name="立ち絵", value="立ち絵"),
    app_commands.Choice(name="1枚絵", value="1枚絵"),
    app_commands.Choice(name="SD", value="SD"),
    app_commands.Choice(name="その他", value="その他"),
]


def resolve_event_name(explicit_event_name: str | None, user_id: str) -> str | None:
    if explicit_event_name:
        return explicit_event_name
    return get_current_event(user_id)


def register_task_command(
    bot: commands.Bot,
    openai_client: Any,
    notion: Any,
    notion_db_id: str | None,
    event_database_id: str | None,
    fanfic_database_id: str | None,
    get_database_schema_config: Callable[[str], tuple[str, dict[str, set[str]]]],
    build_select_property: Callable[[str, str | None, dict[str, set[str]], list[str]], dict | None],
    notion_prop_schedule_date: str,
    notion_prop_category: str,
    notion_prop_event: str,
    notion_prop_work_title: str,
    notion_prop_done: str,
) -> None:
    @bot.tree.command(name="task", description="作品の工程タスクを Notion に登録")
    @app_commands.describe(
        作品名="作品名を入力してください",
        締切日="締切日を YYYY-MM-DD 形式で入力してください",
        作業種別="SCHEDULE DB のカテゴリに対応する作業種別です",
        作品種別="FANFIC DB の分類タグに対応する作品種別です",
        イベント名="未入力の場合は /event で設定した current_event を使います",
    )
    @app_commands.choices(
        作業種別=WORK_CATEGORY_CHOICES,
        作品種別=WORK_TYPE_CHOICES,
    )
    async def add_task(
        interaction: discord.Interaction,
        作品名: str,
        締切日: str,
        作業種別: app_commands.Choice[str],
        作品種別: app_commands.Choice[str],
        イベント名: str | None = None,
    ) -> None:
        await interaction.response.defer()

        try:
            datetime.strptime(締切日, "%Y-%m-%d")
        except ValueError:
            await interaction.followup.send(
                "日付形式が正しくありません。\n形式: YYYY-MM-DD（例: 2026-05-20）"
            )
            return

        resolved_event_name = resolve_event_name(イベント名, str(interaction.user.id))
        if not resolved_event_name:
            await interaction.followup.send(EVENT_REQUIRED_MESSAGE)
            return

        resolved_notion_db_id = notion_db_id or os.getenv("NOTION_DATABASE_ID")
        resolved_event_database_id = event_database_id or os.getenv("NOTION_EVENT_DATABASE_ID")
        resolved_fanfic_database_id = fanfic_database_id or os.getenv("NOTION_FANFIC_DATABASE_ID")
        if not resolved_notion_db_id:
            await interaction.followup.send("NOTION_DATABASE_ID が設定されていません。")
            return

        try:
            tasks_list = generate_task_plan(
                openai_client=openai_client,
                work_title=作品名,
                due_date=締切日,
                work_category=作業種別.value,
                work_type=作品種別.value,
            )
            result = execute_task_registration(
                notion=notion,
                notion_db_id=resolved_notion_db_id,
                event_database_id=resolved_event_database_id,
                fanfic_database_id=resolved_fanfic_database_id,
                tasks_list=tasks_list,
                work_title=作品名,
                work_category=作業種別.value,
                work_type=作品種別.value,
                event_name=resolved_event_name,
                get_database_schema_config=get_database_schema_config,
                build_select_property=build_select_property,
                notion_prop_schedule_date=notion_prop_schedule_date,
                notion_prop_category=notion_prop_category,
                notion_prop_event=notion_prop_event,
                notion_prop_work_title=notion_prop_work_title,
                notion_prop_done=notion_prop_done,
            )
        except Exception as exc:
            await interaction.followup.send(f"エラー: {exc}")
            return

        embed = discord.Embed(
            title="プロジェクト自動分解完了！",
            description=f"**{作品名}** を {result.created_count} 件のタスクに登録しました",
            color=discord.Color.green(),
        )
        task_text = "\n".join(
            f"**{task['task_name']}** → {task['deadline']}"
            for task in sorted(result.tasks_list, key=lambda item: item["deadline"])
        )
        embed.add_field(name="スケジュール", value=task_text[:1024], inline=False)
        if result.sync_messages:
            embed.add_field(
                name="同期結果",
                value="\n".join(f"- {message}" for message in result.sync_messages)[:1024],
                inline=False,
            )
        if result.warning_messages:
            embed.add_field(
                name="Notion設定との不一致",
                value="\n".join(f"- {message}" for message in result.warning_messages)[:1024],
                inline=False,
            )
        if result.skipped_duplicate_count:
            embed.add_field(
                name="重複スキップ",
                value=f"{result.skipped_duplicate_count} 件は既存タスクのため作成をスキップしました。",
                inline=False,
            )
        await interaction.followup.send(embed=embed)
