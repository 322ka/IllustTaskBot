from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.services.db_service import get_current_event
from src.services.log_service import send_log
from src.services.progress_service import (
    PROGRESS_STATUS_DONE,
    PROGRESS_STATUS_IN_PROGRESS,
    PROGRESS_STATUS_NOT_STARTED,
    build_progress_feedback,
    get_estimated_hours,
    save_progress_record,
)


PROGRESS_STATUS_CHOICES = [
    app_commands.Choice(name=PROGRESS_STATUS_NOT_STARTED, value=PROGRESS_STATUS_NOT_STARTED),
    app_commands.Choice(name=PROGRESS_STATUS_IN_PROGRESS, value=PROGRESS_STATUS_IN_PROGRESS),
    app_commands.Choice(name=PROGRESS_STATUS_DONE, value=PROGRESS_STATUS_DONE),
]


def register_progress_command(bot: commands.Bot) -> None:
    @bot.tree.command(name="progress", description="作品工程の実績時間と進捗状態を記録")
    @app_commands.rename(
        work_title="作品名",
        step_name="工程名",
        actual_hours="実績時間",
        progress_status="状態",
        event_name="イベント名",
        memo="メモ",
    )
    @app_commands.describe(
        work_title="進捗を記録したい作品名",
        step_name="工程名を入力してください",
        actual_hours="この工程で実際にかかった時間",
        progress_status="未着手 / 進行中 / 完了",
        event_name="未入力なら /event の current_event を使います",
        memo="補足メモがあれば入力してください",
    )
    @app_commands.choices(progress_status=PROGRESS_STATUS_CHOICES)
    async def progress(
        interaction: discord.Interaction,
        work_title: str,
        step_name: str,
        actual_hours: float,
        progress_status: app_commands.Choice[str],
        event_name: str | None = None,
        memo: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if actual_hours < 0:
            await interaction.followup.send("実績時間は 0 以上で入力してください。", ephemeral=True)
            return

        resolved_event_name = event_name or get_current_event(str(interaction.user.id))
        if not resolved_event_name:
            await interaction.followup.send(
                "イベント名が指定されていません。先に /event で設定するか、/progress に イベント名 を指定してください。",
                ephemeral=True,
            )
            return

        estimated_hours = get_estimated_hours(
            user_id=str(interaction.user.id),
            event_name=resolved_event_name,
            work_title=work_title,
            step_name=step_name,
        )
        updated_at = save_progress_record(
            user_id=str(interaction.user.id),
            event_name=resolved_event_name,
            work_title=work_title,
            step_name=step_name,
            estimated_hours=estimated_hours,
            actual_hours=actual_hours,
            progress_status=progress_status.value,
            memo=memo,
        )

        variance_hours = None if estimated_hours is None else round(actual_hours - estimated_hours, 2)
        comment = build_progress_feedback(
            variance_hours=variance_hours,
            status=progress_status.value,
        )

        lines = [
            "実績を記録しました。",
            f"イベント名: {resolved_event_name}",
            f"作品名: {work_title}",
            f"工程名: {step_name}",
            f"状態: {progress_status.value}",
            f"実績時間: {actual_hours:.1f}h",
        ]
        if estimated_hours is not None:
            lines.append(f"見積時間: {estimated_hours:.1f}h")
            lines.append(f"差分: {variance_hours:+.1f}h")
        else:
            lines.append("見積時間: 未登録")
        if memo:
            lines.append(f"メモ: {memo}")
        lines.append(f"コメント: {comment}")
        lines.append(f"更新時刻: {updated_at}")

        response_text = "\n".join(lines)
        await interaction.followup.send(response_text, ephemeral=True)
        await send_log(
            bot,
            content=f"[progress] user={interaction.user}\n{response_text}"[:1900],
        )
