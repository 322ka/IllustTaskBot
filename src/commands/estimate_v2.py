from __future__ import annotations

from datetime import datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.commands.task import WORK_CATEGORY_CHOICES, WORK_TYPE_CHOICES
from src.models.estimate_templates import (
    DEFAULT_ESTIMATE_TEMPLATE,
    ESTIMATE_TEMPLATES,
    EstimateStep,
)
from src.services.ai_service import apply_ai_estimate_adjustment
from src.services.db_service import get_current_event


ESTIMATE_EVENT_REQUIRED_MESSAGE = (
    "イベント名が指定されていません。先に /event で設定するか、"
    "/estimate に イベント名 を指定してください。"
)

DIFFICULTY_CHOICES = [
    app_commands.Choice(name="低", value="低"),
    app_commands.Choice(name="中", value="中"),
    app_commands.Choice(name="高", value="高"),
]


def resolve_event_name(explicit_event_name: str | None, user_id: str) -> str | None:
    if explicit_event_name:
        return explicit_event_name
    return get_current_event(user_id)


def get_estimate_template(work_type: str) -> list[EstimateStep]:
    return ESTIMATE_TEMPLATES.get(work_type, DEFAULT_ESTIMATE_TEMPLATE)


def build_simple_commentary(total_hours: float, days_until_due: int) -> str:
    if days_until_due < 0:
        return "締切を過ぎています。別案の検討が必要です。"
    if days_until_due <= 3 or total_hours / max(days_until_due, 1) >= 4:
        return "厳しめです。優先順位の整理とバッファ確保をおすすめします。"
    if days_until_due <= 7 or total_hours / max(days_until_due, 1) >= 2:
        return "ややタイトですが調整可能です。"
    return "余裕ありです。バッファを取りやすい見積です。"


def build_simple_schedule_lines(
    due_date: datetime.date,
    steps: list[EstimateStep],
) -> list[str]:
    schedule_lines: list[str] = []
    current_date = due_date

    for step in reversed(steps):
        schedule_lines.append(
            f"{current_date.strftime('%Y-%m-%d')} : {step['step_name']} ({step['hours']:.1f}h)"
        )
        current_date = current_date.fromordinal(current_date.toordinal() - 1)

    return list(reversed(schedule_lines))


def build_estimate_embed(
    *,
    event_name: str,
    work_title: str,
    work_category: str,
    work_type: str,
    due_date: datetime.date,
    steps: list[EstimateStep],
    total_hours: float,
    commentary: str,
    schedule_lines: list[str],
    difficulty: str | None,
    using_ai: bool,
    ai_summary: str | None,
) -> discord.Embed:
    step_lines = "\n".join(
        f"- {step['step_name']}: {step['hours']:.1f}h"
        for step in steps
    )
    schedule_text = "\n".join(f"- {line}" for line in schedule_lines)
    days_until_due = (due_date - datetime.now().date()).days

    embed = discord.Embed(
        title="見積結果（AI補正あり）" if using_ai else "見積結果",
        description=f"**{work_title}** の見積とスケジュール案です。",
        color=discord.Color.blue(),
    )
    embed.add_field(name="イベント名", value=event_name, inline=False)
    embed.add_field(name="作品名", value=work_title, inline=False)
    embed.add_field(name="作業種別", value=work_category, inline=True)
    embed.add_field(name="作品種別", value=work_type, inline=True)
    embed.add_field(name="難易度", value=difficulty or "未指定", inline=True)
    embed.add_field(name="工程一覧", value=step_lines[:1024], inline=False)
    embed.add_field(name="合計時間", value=f"{total_hours:.1f}時間", inline=True)
    embed.add_field(name="締切まで", value=f"{days_until_due}日", inline=True)
    embed.add_field(name="所感", value=commentary[:1024], inline=False)
    embed.add_field(name="簡易スケジュール案", value=schedule_text[:1024], inline=False)

    if using_ai and ai_summary:
        embed.add_field(name="AI補足", value=ai_summary[:1024], inline=False)
    elif not using_ai:
        embed.add_field(
            name="表示モード",
            value="AI補正が使えなかったため、簡易見積を表示しています。",
            inline=False,
        )

    return embed


def register_estimate_command(bot: commands.Bot, openai_client: Any | None = None) -> None:
    @bot.tree.command(name="estimate", description="作品の見積と簡易スケジュール案を確認")
    @app_commands.describe(
        作品名="作品名を入力してください",
        締切日="締切日を YYYY-MM-DD 形式で入力してください",
        作業種別="SCHEDULE DB のカテゴリに対応する作業種別です",
        作品種別="テンプレ工程と FANFIC DB の分類タグに対応する作品種別です",
        難易度="任意です。AI補正の参考にします",
        イベント名="未入力の場合は /event で設定した current_event を使います",
    )
    @app_commands.choices(
        作業種別=WORK_CATEGORY_CHOICES,
        作品種別=WORK_TYPE_CHOICES,
        難易度=DIFFICULTY_CHOICES,
    )
    async def estimate(
        interaction: discord.Interaction,
        作品名: str,
        締切日: str,
        作業種別: app_commands.Choice[str],
        作品種別: app_commands.Choice[str],
        難易度: app_commands.Choice[str] | None = None,
        イベント名: str | None = None,
    ) -> None:
        await interaction.response.defer()

        try:
            due_date = datetime.strptime(締切日, "%Y-%m-%d").date()
        except ValueError:
            await interaction.followup.send(
                "日付形式が正しくありません。\n形式: YYYY-MM-DD（例: 2026-05-20）"
            )
            return

        resolved_event_name = resolve_event_name(イベント名, str(interaction.user.id))
        if not resolved_event_name:
            await interaction.followup.send(ESTIMATE_EVENT_REQUIRED_MESSAGE)
            return

        template = [dict(step) for step in get_estimate_template(作品種別.value)]
        simple_total_hours = sum(step["hours"] for step in template)
        simple_schedule_lines = build_simple_schedule_lines(due_date, template)
        simple_commentary = build_simple_commentary(
            simple_total_hours,
            (due_date - datetime.now().date()).days,
        )

        ai_result = apply_ai_estimate_adjustment(
            openai_client=openai_client,
            event_name=resolved_event_name,
            work_title=作品名,
            work_category=作業種別.value,
            work_type=作品種別.value,
            difficulty=難易度.value if 難易度 else None,
            due_date=due_date.isoformat(),
            template_steps=template,
        )

        if ai_result:
            adjusted_steps = ai_result["adjusted_steps"]
            total_hours = ai_result["total_hours"]
            commentary = ai_result["commentary"]
            schedule_lines = ai_result["schedule_plan"]
            ai_summary = ai_result["buffer_comment"]
            using_ai = True
        else:
            adjusted_steps = template
            total_hours = simple_total_hours
            commentary = simple_commentary
            schedule_lines = simple_schedule_lines
            ai_summary = None
            using_ai = False

        embed = build_estimate_embed(
            event_name=resolved_event_name,
            work_title=作品名,
            work_category=作業種別.value,
            work_type=作品種別.value,
            due_date=due_date,
            steps=adjusted_steps,
            total_hours=total_hours,
            commentary=commentary,
            schedule_lines=schedule_lines,
            difficulty=難易度.value if 難易度 else None,
            using_ai=using_ai,
            ai_summary=ai_summary,
        )

        await interaction.followup.send(embed=embed)
