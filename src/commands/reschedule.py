from __future__ import annotations

from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from src.services.db_service import get_current_event
from src.services.google_calendar_service import list_events, summarize_events
from src.services.log_runtime_service import send_log
from src.services.progress_service import build_reschedule_suggestions, build_work_progress_summaries


def _build_calendar_context_text(summaries: list, event_name: str | None) -> str | None:
    if not summaries:
        return None

    future_due_dates = [summary.due_date for summary in summaries if summary.days_until_due >= 0]
    if not future_due_dates:
        return None

    latest_due_date = max(datetime.fromisoformat(due_date).date() for due_date in future_due_dates)
    events, error = list_events(
        calendar_id=None,
        time_min=datetime.combine(datetime.now().date(), datetime.min.time()),
        time_max=datetime.combine(latest_due_date, datetime.max.time()),
        max_results=50,
    )
    if error:
        return None

    summary = summarize_events(events)
    parts: list[str] = []
    if summary.all_day_count:
        parts.append(f"終日予定 {summary.all_day_count}日")
    if summary.semi_all_day_count:
        parts.append(f"準終日予定 {summary.semi_all_day_count}日")
    if summary.light_count:
        parts.append(f"軽い予定 {summary.light_count}日")
    if not parts:
        return None
    return "Google予定: " + " / ".join(parts)


def register_reschedule_command(bot: commands.Bot) -> None:
    @bot.tree.command(name="reschedule", description="進捗と締切から再調整の優先順位を提案")
    @app_commands.rename(event_name="イベント名")
    @app_commands.describe(
        event_name="未入力なら current_event を優先し、無ければ全体を集計します",
    )
    async def reschedule(
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
                "再調整提案に使える見積または実績がまだありません。先に /estimate や /progress を使ってください。",
                ephemeral=True,
            )
            return

        suggestions = build_reschedule_suggestions(
            user_id=str(interaction.user.id),
            event_name=resolved_event_name,
            today=datetime.now().date(),
        )

        lines = ["再スケジュール案です。"]
        if resolved_event_name:
            lines.append(f"イベント: {resolved_event_name}")
        if suggestions["priority_lines"]:
            lines.append("優先して着手したい作品:")
            lines.extend(f"- {line}" for line in suggestions["priority_lines"])
        if suggestions["focus_lines"]:
            lines.append("今週中に進めたい工程:")
            lines.extend(f"- {line}" for line in suggestions["focus_lines"])
        if suggestions["delay_lines"]:
            lines.append("後ろ倒し候補:")
            lines.extend(f"- {line}" for line in suggestions["delay_lines"])

        urgent_lines = [
            f"{summary.work_title}（締切まであと{summary.days_until_due}日 / 未完了{summary.incomplete_steps}工程）"
            for summary in summaries
            if summary.days_until_due <= 7 and summary.incomplete_steps > 0
        ][:3]
        if urgent_lines:
            lines.append("危険な締切:")
            lines.extend(f"- {line}" for line in urgent_lines)

        calendar_context = _build_calendar_context_text(summaries, resolved_event_name)
        if calendar_context:
            lines.append(calendar_context)

        response_text = "\n".join(lines)
        await interaction.followup.send(response_text, ephemeral=True)
        await send_log(
            bot,
            content=f"[reschedule] user={interaction.user}\n{response_text}"[:1900],
        )
