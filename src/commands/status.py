from __future__ import annotations

from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from src.services.db_service import get_current_event
from src.services.progress_service import build_work_progress_summaries


def register_status_command(bot: commands.Bot) -> None:
    @bot.tree.command(name="status", description="制作物の危険度と進捗状況を確認")
    @app_commands.rename(event_name="イベント名")
    @app_commands.describe(
        event_name="未入力なら current_event を優先し、無ければ全体を集計します",
    )
    async def status(
        interaction: discord.Interaction,
        event_name: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        resolved_event_name = event_name or get_current_event(str(interaction.user.id))
        summaries = build_work_progress_summaries(
            user_id=str(interaction.user.id),
            event_name=resolved_event_name,
            today=datetime.now().date(),
        )

        if not summaries:
            await interaction.followup.send(
                "進捗集計に使える見積または実績がまだありません。先に /estimate や /progress を使ってください。",
                ephemeral=True,
            )
            return

        lines = []
        for summary in summaries[:5]:
            lines.append(
                f"{summary.danger_label}: {summary.work_title}"
                f"（締切まであと{summary.days_until_due}日 / 未完了{summary.incomplete_steps}工程 / 見積差{summary.variance_hours:+.1f}h）"
            )
            if summary.next_steps:
                lines.append(f"  次に見る工程: {', '.join(summary.next_steps[:2])}")

        header = (
            f"イベント: {resolved_event_name}" if resolved_event_name else "イベント横断で集計"
        )
        await interaction.followup.send(
            "現在の進捗状況です。\n"
            f"{header}\n"
            + "\n".join(lines),
            ephemeral=True,
        )
