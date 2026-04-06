from __future__ import annotations

from datetime import datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.commands.task import WORK_CATEGORY_CHOICES, WORK_TYPE_CHOICES
from src.services.google_calendar_service import list_events, summarize_events
from src.services.estimate_runtime_ai_service import request_estimate_adjustment
from src.services.estimate_runtime_service import (
    ESTIMATE_EVENT_REQUIRED_MESSAGE,
    build_simple_estimate,
    resolve_estimate_event_name,
)


DIFFICULTY_CHOICES = [
    app_commands.Choice(name="低", value="低"),
    app_commands.Choice(name="中", value="中"),
    app_commands.Choice(name="高", value="高"),
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
        return "余裕を確保する前提で補正した見積です。"
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
        "OpenAI client is not configured.": "OpenAI client が未設定です。",
        "AI response was empty.": "AI の応答が空でした。",
        "adjusted_steps shape is invalid.": "adjusted_steps の形式が不正です。",
        "schedule_plan shape is invalid.": "schedule_plan の形式が不正です。",
        "commentary fields are invalid.": "AI 補足文の形式が不正です。",
        "step data shape is invalid.": "工程データの形式が不正です。",
        "schedule_plan is empty.": "schedule_plan が空でした。",
    }
    return mapping.get(reason, reason)


def _preview_dates(dates: list[str]) -> str:
    return ", ".join(dates[:5])


def _build_calendar_commentary_suffix(
    *,
    all_day_count: int,
    semi_all_day_count: int,
    light_count: int,
) -> str:
    parts: list[str] = []
    if all_day_count:
        parts.append(f"終日予定が{all_day_count}日")
    if semi_all_day_count:
        parts.append(f"準終日予定が{semi_all_day_count}日")
    if light_count:
        parts.append(f"軽い予定が{light_count}日")
    if not parts:
        return ""
    return "カレンダー上で" + "、".join(parts) + "あります。"


def _apply_calendar_pressure_to_commentary(
    *,
    base_commentary: str,
    all_day_count: int,
    semi_all_day_count: int,
    light_count: int,
) -> str:
    if "締切を過ぎています" in base_commentary:
        return base_commentary

    severity = 0
    if "厳しめです" in base_commentary:
        severity = 2
    elif "ややタイトです" in base_commentary:
        severity = 1

    if all_day_count >= 2:
        severity += 1
    if all_day_count >= 4:
        severity += 1
    if semi_all_day_count >= 1:
        severity += 1

    severity = min(severity, 2)
    if severity >= 2:
        adjusted_commentary = "厳しめです。優先順位の整理とバッファ確保をおすすめします。"
    elif severity == 1:
        adjusted_commentary = "ややタイトですが調整可能です。"
    else:
        adjusted_commentary = "余裕ありです。バッファを取りやすい見積です。"

    suffix = _build_calendar_commentary_suffix(
        all_day_count=all_day_count,
        semi_all_day_count=semi_all_day_count,
        light_count=light_count,
    )
    if suffix:
        return f"{adjusted_commentary} {suffix}"
    return adjusted_commentary


def _build_ai_calendar_context(calendar_summary: Any | None) -> dict[str, Any]:
    if calendar_summary is None:
        return {
            "all_day_count": 0,
            "semi_all_day_count": 0,
            "light_count": 0,
            "all_day_dates": [],
            "semi_all_day_dates": [],
            "light_dates": [],
        }
    return {
        "all_day_count": calendar_summary.all_day_count,
        "semi_all_day_count": calendar_summary.semi_all_day_count,
        "light_count": calendar_summary.light_count,
        "all_day_dates": calendar_summary.all_day_dates[:5],
        "semi_all_day_dates": calendar_summary.semi_all_day_dates[:5],
        "light_dates": calendar_summary.light_dates[:5],
    }


def _build_calendar_note(
    *,
    due_date: datetime.date,
) -> tuple[str | None, str | None, Any | None]:
    today = datetime.now().date()
    if due_date < today:
        return None, None, None

    events, error = list_events(
        calendar_id=None,
        time_min=datetime.combine(today, datetime.min.time()),
        time_max=datetime.combine(due_date, datetime.max.time()),
        max_results=50,
    )
    if error:
        print(f"estimate.calendar skipped: {error}")
        return None, error, None

    summary = summarize_events(events)
    if (
        summary.all_day_count == 0
        and summary.semi_all_day_count == 0
        and summary.light_count == 0
    ):
        return "期間中の大きな予定は見つかりませんでした。", None, summary

    note_parts: list[str] = []
    if summary.all_day_count:
        days = _preview_dates(summary.all_day_dates)
        note_parts.append(f"終日予定: {summary.all_day_count}日（{days}）")
    if summary.semi_all_day_count:
        days = _preview_dates(summary.semi_all_day_dates)
        note_parts.append(f"準終日予定: {summary.semi_all_day_count}日（{days}）")
    if summary.light_count:
        days = _preview_dates(summary.light_dates)
        note_parts.append(f"軽い予定あり: {summary.light_count}日（{days}）")
    return "。".join(note_parts) + "。", None, summary


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
        title="見積結果（AI補正版）" if using_ai else "見積結果（簡易見積）",
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
    embed.add_field(
        name="簡易スケジュール案",
        value="\n".join(f"- {line}" for line in schedule_lines)[:1024],
        inline=False,
    )
    if calendar_note:
        embed.add_field(name="予定考慮", value=calendar_note[:1024], inline=False)
    if using_ai and ai_note:
        embed.add_field(name="AI補足", value=ai_note[:1024], inline=False)
    if not using_ai:
        fallback_text = (
            "AI補正が使えなかったため、"
            "簡易見積を表示しています。"
        )
        if ai_note:
            fallback_text = f"{fallback_text}\n{ai_note}"
        embed.add_field(name="表示モード", value=fallback_text[:1024], inline=False)
    return embed


def register_estimate_command(bot: commands.Bot, openai_client: Any | None = None) -> None:
    @bot.tree.command(name="estimate", description="作品の見積と簡易スケジュール案を確認")
    @app_commands.rename(
        work_title="作品名",
        due_date="締切日",
        work_category="作業種別",
        work_type="作品種別",
        difficulty="難易度",
        event_name="イベント名",
    )
    @app_commands.describe(
        work_title="作品名を入力してください",
        due_date="締切日を YYYY-MM-DD 形式で入力してください",
        work_category="SCHEDULE DB のカテゴリに対応する作業種別です",
        work_type="テンプレ工程と FANFIC DB の分類タグに対応する作品種別です",
        difficulty="任意です。AI補正の参考にします",
        event_name="未入力の場合は /event で設定した current_event を使います",
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
            calendar_summary = None
            using_ai = False
            steps = simple_result.steps
            total_hours = simple_result.total_hours
            commentary = simple_result.commentary
            schedule_lines = simple_result.schedule_lines

            stage = "calendar_context"
            calendar_note, calendar_error, calendar_summary = _build_calendar_note(due_date=parsed_due_date)
            if calendar_error:
                calendar_note = None

            if calendar_summary:
                commentary = _apply_calendar_pressure_to_commentary(
                    base_commentary=commentary,
                    all_day_count=calendar_summary.all_day_count,
                    semi_all_day_count=calendar_summary.semi_all_day_count,
                    light_count=calendar_summary.light_count,
                )

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
                calendar_context=_build_ai_calendar_context(calendar_summary),
            )

            if ai_outcome.used_ai and ai_outcome.result:
                using_ai = True
                steps = ai_outcome.result.adjusted_steps
                total_hours = ai_outcome.result.total_hours
                commentary = _normalize_ai_commentary(
                    ai_outcome.result.commentary,
                    commentary,
                )
                schedule_lines = _normalize_ai_schedule_lines(
                    ai_outcome.result.schedule_plan,
                    simple_result.schedule_lines,
                )
                ai_note = _normalize_ai_buffer_comment(ai_outcome.result.buffer_comment)
            elif ai_outcome.failure_reason:
                ai_note = (
                    "AI補正は使えませんでした: "
                    f"{_localize_ai_failure_reason(ai_outcome.failure_reason)}"
                )

            if calendar_summary:
                commentary = _apply_calendar_pressure_to_commentary(
                    base_commentary=commentary,
                    all_day_count=calendar_summary.all_day_count,
                    semi_all_day_count=calendar_summary.semi_all_day_count,
                    light_count=calendar_summary.light_count,
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
                    "日付形式が正しくありません。"
                    "形式: YYYY-MM-DD（例: 2026-05-20）"
                )
                return
            print(f"estimate error at {stage}: ValueError")
            await interaction.followup.send(
                "見積処理中に入力値の解釈でエラーが発生しました。"
                "内容を確認して再実行してください。"
            )
        except Exception as exc:
            print(f"estimate error at {stage}: {type(exc).__name__}: {exc}")
            await interaction.followup.send(
                f"見積処理中にエラーが発生しました。失敗段階: {stage}"
            )
