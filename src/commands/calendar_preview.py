from __future__ import annotations

from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from src.services.google_calendar_service import list_events


def _normalize_calendar_event_title(title: str) -> str:
    normalized = (title or "").strip()
    if normalized in {"", "(no title)"}:
        return "予定あり"
    return normalized


def _format_calendar_event_time(start: str, is_all_day: bool) -> str:
    if is_all_day:
        return f"{start} (\u7d42\u65e5)"
    return start


def register_calendar_preview_command(bot: commands.Bot) -> None:
    @bot.tree.command(name="calendar_preview", description="\u6307\u5b9a\u671f\u9593\u306e Google \u30ab\u30ec\u30f3\u30c0\u30fc\u4e88\u5b9a\u3092\u78ba\u8a8d")
    @app_commands.describe(
        start_date="\u958b\u59cb\u65e5\u3092 YYYY-MM-DD \u5f62\u5f0f\u3067\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044",
        end_date="\u7d42\u4e86\u65e5\u3092 YYYY-MM-DD \u5f62\u5f0f\u3067\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044",
        calendar_id="\u672a\u5165\u529b\u306e\u5834\u5408\u306f primary \u307e\u305f\u306f env \u306e GOOGLE_CALENDAR_ID \u3092\u4f7f\u3044\u307e\u3059",
    )
    async def calendar_preview(
        interaction: discord.Interaction,
        start_date: str,
        end_date: str,
        calendar_id: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            await interaction.followup.send(
                "\u65e5\u4ed8\u5f62\u5f0f\u304c\u6b63\u3057\u304f\u3042\u308a\u307e\u305b\u3093\u3002"
                "\u5f62\u5f0f: YYYY-MM-DD\uff08\u4f8b: 2026-05-01\uff09",
                ephemeral=True,
            )
            return

        events, error = list_events(
            calendar_id=calendar_id,
            time_min=start_dt,
            time_max=end_dt,
            max_results=10,
        )
        if error:
            await interaction.followup.send(
                "\u30ab\u30ec\u30f3\u30c0\u30fc\u8aad\u307f\u53d6\u308a\u3092\u958b\u59cb\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\n"
                f"{error}",
                ephemeral=True,
            )
            return

        preview_lines = []
        for event in events[:5]:
            preview_lines.append(
                f"- {_normalize_calendar_event_title(event.summary)} / {_format_calendar_event_time(event.start, event.is_all_day)}"
            )

        embed = discord.Embed(
            title="\u30ab\u30ec\u30f3\u30c0\u30fc\u4e88\u5b9a\u78ba\u8a8d",
            description=(
                f"\u671f\u9593: {start_date} \u301c {end_date}\n"
                f"\u4e88\u5b9a\u4ef6\u6570: {len(events)}"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="\u4e88\u5b9a\u30d7\u30ec\u30d3\u30e5\u30fc",
            value="\n".join(preview_lines)[:1024] if preview_lines else "\u4e88\u5b9a\u306f\u3042\u308a\u307e\u305b\u3093",
            inline=False,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)
