from __future__ import annotations

from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from src.commands.task import WORK_CATEGORY_CHOICES, WORK_TYPE_CHOICES
from src.models.templates import DEFAULT_ESTIMATE_TEMPLATE, ESTIMATE_TEMPLATES
from src.services.db_service import get_current_event


ESTIMATE_EVENT_REQUIRED_MESSAGE = (
    "イベント名が指定されていません。先に /event で設定するか、"
    "/estimate に イベント名 を指定してください。"
)


def resolve_event_name(explicit_event_name: str | None, user_id: str) -> str | None:
    if explicit_event_name:
        return explicit_event_name

    return get_current_event(user_id)


def get_estimate_template(work_type: str) -> list[dict]:
    return ESTIMATE_TEMPLATES.get(work_type, DEFAULT_ESTIMATE_TEMPLATE)


def build_estimate_commentary(total_hours: float, days_until_due: int) -> str:
    if days_until_due < 0:
        return "締切を過ぎています。かなり厳しいです。"
    if days_until_due <= 3 or total_hours / max(days_until_due, 1) >= 4:
        return "厳しめです。早めの着手をおすすめします。"
    if days_until_due <= 7 or total_hours / max(days_until_due, 1) >= 2:
        return "ややタイトですが調整可能です。"
    return "余裕ありです。バッファを取りやすい想定です。"


def register_estimate_command(bot: commands.Bot) -> None:
    @bot.tree.command(name="estimate", description="作品の簡易見積とスケジュール所感を確認")
    @app_commands.describe(
        作品名="作品名を入力してください",
        締切日="締切日を YYYY-MM-DD 形式で入力してください",
        作業種別="作業の区分です",
        作品種別="見積テンプレに使う作品種別です",
        イベント名="未入力の場合は /event で設定した現在イベントを使います",
    )
    @app_commands.choices(
        作業種別=WORK_CATEGORY_CHOICES,
        作品種別=WORK_TYPE_CHOICES,
    )
    async def estimate(
        interaction: discord.Interaction,
        作品名: str,
        締切日: str,
        作業種別: app_commands.Choice[str],
        作品種別: app_commands.Choice[str],
        イベント名: str | None = None,
    ):
        await interaction.response.defer()

        try:
            due_date = datetime.strptime(締切日, "%Y-%m-%d").date()
        except ValueError:
            await interaction.followup.send(
                "❌ 日付形式が正しくありません。\n形式: YYYY-MM-DD（例：2026-05-20）"
            )
            return

        resolved_event_name = resolve_event_name(イベント名, str(interaction.user.id))
        if not resolved_event_name:
            await interaction.followup.send(ESTIMATE_EVENT_REQUIRED_MESSAGE)
            return

        template = get_estimate_template(作品種別.value)
        total_hours = sum(step["hours"] for step in template)
        days_until_due = (due_date - datetime.now().date()).days
        commentary = build_estimate_commentary(total_hours, days_until_due)

        step_lines = "\n".join(
            f"- {step['step_name']}: {step['hours']:.1f}h"
            for step in template
        )

        embed = discord.Embed(
            title="📐 簡易見積",
            description=f"**{作品名}** の簡易見積を作成しました。",
            color=discord.Color.blue(),
        )
        embed.add_field(name="🎪 イベント名", value=resolved_event_name, inline=False)
        embed.add_field(name="🖼️ 作品名", value=作品名, inline=False)
        embed.add_field(name="🛠️ 作業種別", value=作業種別.value, inline=True)
        embed.add_field(name="📦 作品種別", value=作品種別.value, inline=True)
        embed.add_field(name="📋 工程一覧", value=step_lines[:1024], inline=False)
        embed.add_field(name="⏱️ 合計時間", value=f"{total_hours:.1f}時間", inline=True)
        embed.add_field(name="📅 締切まで", value=f"{days_until_due}日", inline=True)
        embed.add_field(name="💬 所感", value=commentary, inline=False)

        await interaction.followup.send(embed=embed)
