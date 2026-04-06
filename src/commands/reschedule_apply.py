from __future__ import annotations

import asyncio
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from src.services.db_service import get_current_event
from src.services.log_runtime_service import send_log
from src.services.task_runtime_service import execute_schedule_reschedule


def register_reschedule_apply_command(
    bot: commands.Bot,
    *,
    notion,
    notion_db_id: str,
    get_database_schema_config,
    notion_prop_schedule_date: str,
    notion_prop_event: str,
    notion_prop_work_title: str,
    notion_prop_done: str,
) -> None:
    @bot.tree.command(name="reschedule_apply", description="既存の未完了タスク日付を再調整します")
    @app_commands.rename(event_name="イベント名")
    @app_commands.describe(
        event_name="未入力なら current_event を使います",
    )
    async def reschedule_apply(
        interaction: discord.Interaction,
        event_name: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        resolved_event_name = event_name or get_current_event(str(interaction.user.id))
        if not resolved_event_name:
            await interaction.followup.send(
                "イベント名が指定されていません。先に /event で設定するか、/reschedule_apply に イベント名 を指定してください。",
                ephemeral=True,
            )
            return

        result = await asyncio.to_thread(
            execute_schedule_reschedule,
            notion=notion,
            notion_db_id=notion_db_id,
            event_name=resolved_event_name,
            user_id=str(interaction.user.id),
            get_database_schema_config=get_database_schema_config,
            notion_prop_schedule_date=notion_prop_schedule_date,
            notion_prop_event=notion_prop_event,
            notion_prop_work_title=notion_prop_work_title,
            notion_prop_done=notion_prop_done,
        )

        lines = [
            "既存タスクの再調整を完了しました。",
            f"イベント名: {resolved_event_name}",
            f"対象件数: {result.target_count}件",
            f"移動件数: {result.moved_count}件",
            f"維持件数: {result.unchanged_count}件",
        ]
        if result.sync_messages:
            lines.append("結果:")
            lines.extend(f"- {message}" for message in result.sync_messages)
        if result.moved_page_urls:
            preview_urls = result.moved_page_urls[:3]
            lines.append(f"SCHEDULEページ: {len(result.moved_page_urls)}件（先頭 {len(preview_urls)} 件）")
            lines.extend(f"- <{url}>" for url in preview_urls)
            if len(result.moved_page_urls) > len(preview_urls):
                lines.append(f"- ほか {len(result.moved_page_urls) - len(preview_urls)} 件")
        if result.warning_messages:
            lines.append("注意:")
            lines.extend(f"- {message}" for message in result.warning_messages[:5])

        response_text = "\n".join(lines)
        await interaction.followup.send(response_text, ephemeral=True)
        await send_log(
            bot,
            content=f"[reschedule_apply] user={interaction.user} event={resolved_event_name}\n{response_text}"[:1900],
        )
