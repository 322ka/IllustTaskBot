from __future__ import annotations

from datetime import datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.commands.task import WORK_CATEGORY_CHOICES, WORK_TYPE_CHOICES
from src.services.google_calendar_service import list_events
from src.services.estimate_runtime_ai_service import request_estimate_adjustment
from src.services.estimate_runtime_service import (
    ESTIMATE_EVENT_REQUIRED_MESSAGE,
    build_simple_estimate,
    resolve_estimate_event_name,
)


DIFFICULTY_CHOICES = [
    app_commands.Choice(name="\u4f4e", value="\u4f4e"),
    app_commands.Choice(name="\u4e2d", value="\u4e2d"),
    app_commands.Choice(name="\u9ad8", value="\u9ad8"),
]


def _looks_english(text: str) -> bool:
    ascii_letters = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
    return ascii_letters >= max(8, len(text) // 4)


def _normalize_ai_commentary(text: str, fallback: str) -> str:
    if not text or _looks_english(text):
        return fallback
    return text


def _normalize_ai_buffer_comment(text: str) -> str:
    if not text or _looks_english(text):
        return "\u4f59\u88d5\u3092\u78ba\u4fdd\u3059\u308b\u524d\u63d0\u3067\u88dc\u6b63\u3057\u305f\u898b\u7a4d\u3067\u3059\u3002"
    return text


def _normalize_ai_schedule_lines(lines: list[str], fallback: list[str]) -> list[str]:
    if not lines:
        return fallback
    english_like_count = sum(1 for line in lines if _looks_english(line))
    if english_like_count >= max(1, len(lines) // 2):
        return fallback
    return lines


def _localize_ai_failure_reason(reason: str) -> str:
    mapping = {
        "OpenAI client is not configured.": "OpenAI client \u304c\u672a\u8a2d\u5b9a\u3067\u3059\u3002",
        "AI response was empty.": "AI \u306e\u5fdc\u7b54\u304c\u7a7a\u3067\u3057\u305f\u3002",
        "adjusted_steps shape is invalid.": "adjusted_steps \u306e\u5f62\u5f0f\u304c\u4e0d\u6b63\u3067\u3059\u3002",
        "schedule_plan shape is invalid.": "schedule_plan \u306e\u5f62\u5f0f\u304c\u4e0d\u6b63\u3067\u3059\u3002",
        "commentary fields are invalid.": "AI \u88dc\u8db3\u6587\u306e\u5f62\u5f0f\u304c\u4e0d\u6b63\u3067\u3059\u3002",
        "step data shape is invalid.": "\u5de5\u7a0b\u30c7\u30fc\u30bf\u306e\u5f62\u5f0f\u304c\u4e0d\u6b63\u3067\u3059\u3002",
        "schedule_plan is empty.": "schedule_plan \u304c\u7a7a\u3067\u3057\u305f\u3002",
    }
    return mapping.get(reason, reason)


def _build_calendar_note(
    *,
    due_date: datetime.date,
) -> tuple[str | None, str | None]:
    today = datetime.now().date()
    if due_date < today:
        return None, None

    events, error = list_events(
        calendar_id=None,
        time_min=datetime.combine(today, datetime.min.time()),
        time_max=datetime.combine(due_date, datetime.max.time()),
        max_results=50,
    )
    if error:
        print(f"estimate.calendar skipped: {error}")
        return None, error

    all_day_dates: list[str] = []
    timed_dates: list[str] = []
    for event in events:
        date_label = event.start.split("T")[0]
        if event.is_all_day:
            all_day_dates.append(date_label)
        else:
            timed_dates.append(date_label)

    unique_all_day = sorted(set(all_day_dates))
    unique_timed = sorted(set(timed_dates))
    if not unique_all_day and not unique_timed:
        return "\u671f\u9593\u4e2d\u306e\u5927\u304d\u306a\u4e88\u5b9a\u306f\u898b\u3064\u304b\u308a\u307e\u305b\u3093\u3067\u3057\u305f\u3002", None

    note_parts: list[str] = []
    if unique_all_day:
        days = ", ".join(unique_all_day[:5])
        note_parts.append(
            f"\u7d42\u65e5\u4e88\u5b9a\u304c {len(unique_all_day)} \u65e5\u3042\u308a\u307e\u3059\uff08{days}\uff09"
        )
    if unique_timed:
        days = ", ".join(unique_timed[:5])
        note_parts.append(
            f"\u6642\u523b\u4ed8\u304d\u4e88\u5b9a\u304c {len(unique_timed)} \u65e5\u3042\u308a\u307e\u3059\uff08{days}\uff09"
        )
    return "\u3002".join(note_parts) + "\u3002", None


def build_estimate_embed(
    *,
    event_name: str,
    work_title: str,
    work_category: str,
    work_type: str,
    difficulty: str | None,
    total_hours: float,
    days_until_due: int,
    commentary: str,
    step_lines: str,
    schedule_lines: list[str],
    using_ai: bool,
    ai_note: str | None,
    calendar_note: str | None,
) -> discord.Embed:
    embed = discord.Embed(
        title="\u898b\u7a4d\u7d50\u679c\uff08AI\u88dc\u6b63\u7248\uff09" if using_ai else "\u898b\u7a4d\u7d50\u679c\uff08\u7c21\u6613\u898b\u7a4d\uff09",
        description=f"**{work_title}** \u306e\u898b\u7a4d\u3068\u30b9\u30b1\u30b8\u30e5\u30fc\u30eb\u6848\u3067\u3059\u3002",
        color=discord.Color.blue(),
    )
    embed.add_field(name="\u30a4\u30d9\u30f3\u30c8\u540d", value=event_name, inline=False)
    embed.add_field(name="\u4f5c\u54c1\u540d", value=work_title, inline=False)
    embed.add_field(name="\u4f5c\u696d\u7a2e\u5225", value=work_category, inline=True)
    embed.add_field(name="\u4f5c\u54c1\u7a2e\u5225", value=work_type, inline=True)
    embed.add_field(name="\u96e3\u6613\u5ea6", value=difficulty or "\u672a\u6307\u5b9a", inline=True)
    embed.add_field(name="\u5de5\u7a0b\u4e00\u89a7", value=step_lines[:1024], inline=False)
    embed.add_field(name="\u5408\u8a08\u6642\u9593", value=f"{total_hours:.1f}\u6642\u9593", inline=True)
    embed.add_field(name="\u7de0\u5207\u307e\u3067", value=f"{days_until_due}\u65e5", inline=True)
    embed.add_field(name="\u6240\u611f", value=commentary[:1024], inline=False)
    embed.add_field(
        name="\u7c21\u6613\u30b9\u30b1\u30b8\u30e5\u30fc\u30eb\u6848",
        value="\n".join(f"- {line}" for line in schedule_lines)[:1024],
        inline=False,
    )
    if calendar_note:
        embed.add_field(name="\u4e88\u5b9a\u8003\u616e", value=calendar_note[:1024], inline=False)
    if using_ai and ai_note:
        embed.add_field(name="AI\u88dc\u8db3", value=ai_note[:1024], inline=False)
    if not using_ai:
        fallback_text = (
            "AI\u88dc\u6b63\u304c\u4f7f\u3048\u306a\u304b\u3063\u305f\u305f\u3081\u3001"
            "\u7c21\u6613\u898b\u7a4d\u3092\u8868\u793a\u3057\u3066\u3044\u307e\u3059\u3002"
        )
        if ai_note:
            fallback_text = f"{fallback_text}\n{ai_note}"
        embed.add_field(name="\u8868\u793a\u30e2\u30fc\u30c9", value=fallback_text[:1024], inline=False)
    return embed


def register_estimate_command(bot: commands.Bot, openai_client: Any | None = None) -> None:
    @bot.tree.command(name="estimate", description="\u4f5c\u54c1\u306e\u898b\u7a4d\u3068\u7c21\u6613\u30b9\u30b1\u30b8\u30e5\u30fc\u30eb\u6848\u3092\u78ba\u8a8d")
    @app_commands.rename(
        work_title="\u4f5c\u54c1\u540d",
        due_date="\u7de0\u5207\u65e5",
        work_category="\u4f5c\u696d\u7a2e\u5225",
        work_type="\u4f5c\u54c1\u7a2e\u5225",
        difficulty="\u96e3\u6613\u5ea6",
        event_name="\u30a4\u30d9\u30f3\u30c8\u540d",
    )
    @app_commands.describe(
        work_title="\u4f5c\u54c1\u540d\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044",
        due_date="\u7de0\u5207\u65e5\u3092 YYYY-MM-DD \u5f62\u5f0f\u3067\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044",
        work_category="SCHEDULE DB \u306e\u30ab\u30c6\u30b4\u30ea\u306b\u5bfe\u5fdc\u3059\u308b\u4f5c\u696d\u7a2e\u5225\u3067\u3059",
        work_type="\u30c6\u30f3\u30d7\u30ec\u5de5\u7a0b\u3068 FANFIC DB \u306e\u5206\u985e\u30bf\u30b0\u306b\u5bfe\u5fdc\u3059\u308b\u4f5c\u54c1\u7a2e\u5225\u3067\u3059",
        difficulty="\u4efb\u610f\u3067\u3059\u3002AI\u88dc\u6b63\u306e\u53c2\u8003\u306b\u3057\u307e\u3059",
        event_name="\u672a\u5165\u529b\u306e\u5834\u5408\u306f /event \u3067\u8a2d\u5b9a\u3057\u305f current_event \u3092\u4f7f\u3044\u307e\u3059",
    )
    @app_commands.choices(
        work_category=WORK_CATEGORY_CHOICES,
        work_type=WORK_TYPE_CHOICES,
        difficulty=DIFFICULTY_CHOICES,
    )
    async def estimate(
        interaction: discord.Interaction,
        work_title: str,
        due_date: str,
        work_category: app_commands.Choice[str],
        work_type: app_commands.Choice[str],
        difficulty: app_commands.Choice[str] | None = None,
        event_name: str | None = None,
    ) -> None:
        stage = "init"
        await interaction.response.defer()

        try:
            stage = "date_parse"
            parsed_due_date = datetime.strptime(due_date, "%Y-%m-%d").date()

            stage = "event_resolve"
            resolved_event_name = resolve_estimate_event_name(
                explicit_event_name=event_name,
                user_id=str(interaction.user.id),
            )
            if not resolved_event_name:
                await interaction.followup.send(ESTIMATE_EVENT_REQUIRED_MESSAGE)
                return

            stage = "simple_estimate"
            simple_result = build_simple_estimate(
                due_date=parsed_due_date,
                work_type=work_type.value,
            )

            ai_note: str | None = None
            calendar_note: str | None = None
            using_ai = False
            steps = simple_result.steps
            total_hours = simple_result.total_hours
            commentary = simple_result.commentary
            schedule_lines = simple_result.schedule_lines

            stage = "calendar_context"
            calendar_note, calendar_error = _build_calendar_note(due_date=parsed_due_date)
            if calendar_error:
                calendar_note = None

            stage = "ai_adjustment"
            ai_outcome = request_estimate_adjustment(
                openai_client=openai_client,
                event_name=resolved_event_name,
                work_title=work_title,
                work_category=work_category.value,
                work_type=work_type.value,
                difficulty=difficulty.value if difficulty else None,
                due_date=parsed_due_date.isoformat(),
                template_steps=simple_result.steps,
            )

            if ai_outcome.used_ai and ai_outcome.result:
                using_ai = True
                steps = ai_outcome.result.adjusted_steps
                total_hours = ai_outcome.result.total_hours
                commentary = _normalize_ai_commentary(
                    ai_outcome.result.commentary,
                    simple_result.commentary,
                )
                schedule_lines = _normalize_ai_schedule_lines(
                    ai_outcome.result.schedule_plan,
                    simple_result.schedule_lines,
                )
                ai_note = _normalize_ai_buffer_comment(ai_outcome.result.buffer_comment)
            elif ai_outcome.failure_reason:
                ai_note = (
                    "AI\u88dc\u6b63\u306f\u4f7f\u3048\u307e\u305b\u3093\u3067\u3057\u305f: "
                    f"{_localize_ai_failure_reason(ai_outcome.failure_reason)}"
                )

            stage = "display"
            step_lines = "\n".join(
                f"- {step['step_name']}: {step['hours']:.1f}h"
                for step in steps
            )
            embed = build_estimate_embed(
                event_name=resolved_event_name,
                work_title=work_title,
                work_category=work_category.value,
                work_type=work_type.value,
                difficulty=difficulty.value if difficulty else None,
                total_hours=total_hours,
                days_until_due=simple_result.days_until_due,
                commentary=commentary,
                step_lines=step_lines,
                schedule_lines=schedule_lines,
                using_ai=using_ai,
                ai_note=ai_note,
                calendar_note=calendar_note,
            )
            await interaction.followup.send(embed=embed)
        except ValueError:
            if stage == "date_parse":
                await interaction.followup.send(
                    "\u65e5\u4ed8\u5f62\u5f0f\u304c\u6b63\u3057\u304f\u3042\u308a\u307e\u305b\u3093\u3002"
                    "\u5f62\u5f0f: YYYY-MM-DD\uff08\u4f8b: 2026-05-20\uff09"
                )
                return
            print(f"estimate error at {stage}: ValueError")
            await interaction.followup.send(
                "\u898b\u7a4d\u51e6\u7406\u4e2d\u306b\u5165\u529b\u5024\u306e\u89e3\u91c8\u3067\u30a8\u30e9\u30fc\u304c\u767a\u751f\u3057\u307e\u3057\u305f\u3002"
                "\u5185\u5bb9\u3092\u78ba\u8a8d\u3057\u3066\u518d\u5b9f\u884c\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
            )
        except Exception as exc:
            print(f"estimate error at {stage}: {type(exc).__name__}: {exc}")
            await interaction.followup.send(
                f"\u898b\u7a4d\u51e6\u7406\u4e2d\u306b\u30a8\u30e9\u30fc\u304c\u767a\u751f\u3057\u307e\u3057\u305f\u3002\u5931\u6557\u6bb5\u968e: {stage}"
            )
