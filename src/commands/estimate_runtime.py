from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import traceback
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from src.commands.task import WORK_CATEGORY_CHOICES, WORK_TYPE_CHOICES
from src.services.db_service import (
    ESTIMATE_EXPIRY_SECONDS,
    get_latest_estimate,
    mark_latest_estimate_task_created,
    save_latest_estimate,
)
from src.services.progress_service import save_estimate_snapshot
from src.services.google_calendar_service import list_events, summarize_events
from src.services.log_runtime_service import send_log
from src.services.estimate_runtime_ai_service import request_estimate_adjustment
from src.services.estimate_runtime_service import (
    ESTIMATE_EVENT_REQUIRED_MESSAGE,
    build_simple_estimate,
    resolve_estimate_event_name,
)
from src.services.task_runtime_service import execute_task_registration, generate_task_plan


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


def _normalize_ai_note(text: str | None, *, using_ai: bool) -> str | None:
    if not text:
        return None
    if using_ai:
        return _normalize_ai_buffer_comment(text)
    return text


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


def _build_calendar_note(*, due_date: datetime.date) -> tuple[str | None, str | None, Any | None]:
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


def _format_notion_link(url: str) -> str:
    return f"<{url}>"


async def _safe_send_ephemeral(interaction: discord.Interaction, message: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception as exc:
        print(f"estimate->task response failed: {type(exc).__name__}: {exc}")


async def _safe_refresh_view(interaction: discord.Interaction, view: discord.ui.View) -> None:
    try:
        await interaction.edit_original_response(view=view)
    except Exception as exc:
        print(f"estimate->task view refresh failed: {type(exc).__name__}: {exc}")


def build_estimate_embed(
    *,
    event_name: str,
    work_title: str,
    work_category: str,
    work_type: str,
    work_type_weight: float,
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
    embed.add_field(name="作品種別補正", value=f"×{work_type_weight:.2f}（{work_type}）", inline=True)
    embed.add_field(name="工程一覧", value=step_lines[:1024], inline=False)
    embed.add_field(name="合計時間", value=f"{total_hours:.1f}時間（補正後）", inline=True)
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
        fallback_text = "AI補正が使えなかったため、簡易見積を表示しています。"
        if ai_note:
            fallback_text = f"{fallback_text}\n{ai_note}"
        embed.add_field(name="表示モード", value=fallback_text[:1024], inline=False)
    embed.set_footer(text="この見積結果をもとに task 化できます。")
    return embed


class EstimateTaskActionView(discord.ui.View):
    def __init__(
        self,
        *,
        bot: commands.Bot,
        owner_user_id: str,
        estimate_created_at: str,
        openai_client: Any | None,
        task_runtime_options: dict[str, Any] | None,
    ) -> None:
        super().__init__(timeout=60 * 60 * 3)
        self.bot = bot
        self.owner_user_id = owner_user_id
        self.estimate_created_at = estimate_created_at
        self.openai_client = openai_client
        self.task_runtime_options = task_runtime_options or {}
        self.is_processed = False
        self.is_processing = False

    @discord.ui.button(label="この内容でタスク作成", style=discord.ButtonStyle.green)
    async def create_task_from_estimate(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if str(interaction.user.id) != self.owner_user_id:
            await _safe_send_ephemeral(interaction, "このボタンは見積を作成した本人のみ使えます。")
            return

        if self.is_processing:
            await _safe_send_ephemeral(interaction, "いま task 化を実行中です。少し待ってから結果を確認してください。")
            return

        if self.is_processed:
            await _safe_send_ephemeral(interaction, "この見積からの task 化はすでに処理済みです。")
            return

        self.is_processing = True
        button.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception as exc:
            print(f"estimate->task button disable failed: {type(exc).__name__}: {exc}")

        record = get_latest_estimate(self.owner_user_id)
        if record is None:
            self.is_processing = False
            button.disabled = False
            await _safe_refresh_view(interaction, self)
            await _safe_send_ephemeral(interaction, "task 化できる見積が見つかりませんでした。もう一度 /estimate を実行してください。")
            return

        if record.estimate_created_at != self.estimate_created_at:
            self.is_processing = False
            button.disabled = False
            await _safe_refresh_view(interaction, self)
            await _safe_send_ephemeral(interaction, "より新しい見積があります。最新の見積結果から task 化してください。")
            return

        created_at = datetime.fromisoformat(record.estimate_created_at)
        if (datetime.now(timezone.utc) - created_at).total_seconds() > ESTIMATE_EXPIRY_SECONDS:
            self.is_processing = False
            button.disabled = False
            await _safe_refresh_view(interaction, self)
            await _safe_send_ephemeral(interaction, "この見積結果は古くなったため失効しました。もう一度 /estimate を実行してください。")
            return

        if record.task_created_at:
            self.is_processing = False
            self.is_processed = True
            await _safe_refresh_view(interaction, self)
            await _safe_send_ephemeral(interaction, "この見積からの task 化はすでに処理済みです。")
            return

        notion_db_id = self.task_runtime_options.get("notion_db_id")
        notion = self.task_runtime_options.get("notion")
        if not notion_db_id or notion is None:
            self.is_processing = False
            button.disabled = False
            await _safe_refresh_view(interaction, self)
            await _safe_send_ephemeral(interaction, "task 化に必要な Notion 設定が不足しています。")
            return

        try:
            tasks_list = await asyncio.to_thread(
                generate_task_plan,
                openai_client=self.openai_client,
                work_title=record.work_title,
                due_date=record.due_date,
                work_category=record.work_category,
                work_type=record.work_type,
            )
            result = await asyncio.to_thread(
                execute_task_registration,
                notion=notion,
                notion_db_id=notion_db_id,
                event_database_id=self.task_runtime_options.get("event_database_id"),
                fanfic_database_id=self.task_runtime_options.get("fanfic_database_id"),
                tasks_list=tasks_list,
                work_title=record.work_title,
                work_category=record.work_category,
                work_type=record.work_type,
                event_name=record.event_name,
                user_id=self.owner_user_id,
                get_database_schema_config=self.task_runtime_options["get_database_schema_config"],
                build_select_property=self.task_runtime_options["build_select_property"],
                notion_prop_schedule_date=self.task_runtime_options["notion_prop_schedule_date"],
                notion_prop_category=self.task_runtime_options["notion_prop_category"],
                notion_prop_event=self.task_runtime_options["notion_prop_event"],
                notion_prop_work_title=self.task_runtime_options["notion_prop_work_title"],
                notion_prop_done=self.task_runtime_options["notion_prop_done"],
            )
        except Exception as exc:
            self.is_processing = False
            button.disabled = False
            await _safe_refresh_view(interaction, self)
            await _safe_send_ephemeral(interaction, f"task 化に失敗しました: {exc}")
            return

        try:
            self.is_processed = True
            self.is_processing = False
            await asyncio.to_thread(mark_latest_estimate_task_created, self.owner_user_id)
            await _safe_refresh_view(interaction, self)

            fanfic_status_message = "FANFIC: 未処理です。"
            if self.task_runtime_options.get("fanfic_database_id"):
                fanfic_status_message = (
                    "FANFIC: 既存ページを利用しました。"
                    if result.fanfic_used_existing
                    else "FANFIC: 新規ページを作成しました。"
                )
                if result.fanfic_page_url is None:
                    fanfic_status_message = "FANFIC: 同期結果を確認してください。"
            else:
                fanfic_status_message = "FANFIC: DB未設定のためスキップしました。"

            result_lines = [
                "見積結果から task 化を完了しました。",
                f"作品名: {record.work_title}",
                f"イベント名: {record.event_name}",
                f"SCHEDULE作成件数: {result.created_count}件",
                f"SCHEDULE重複スキップ: {result.skipped_duplicate_count}件",
                fanfic_status_message,
            ]

            if result.fanfic_page_url:
                result_lines.append(f"FANFICページ: {_format_notion_link(result.fanfic_page_url)}")

            if result.created_schedule_page_urls:
                preview_count = min(3, len(result.created_schedule_page_urls))
                result_lines.append(f"SCHEDULEページ: {len(result.created_schedule_page_urls)}件（先頭 {preview_count} 件）")
                result_lines.extend(
                    f"- {_format_notion_link(url)}"
                    for url in result.created_schedule_page_urls[:preview_count]
                )
                remaining_count = len(result.created_schedule_page_urls) - 3
                if remaining_count > 0:
                    result_lines.append(f"- ほか {remaining_count} 件")

            if result.sync_messages:
                result_lines.append("同期結果:")
                result_lines.extend(f"- {message}" for message in result.sync_messages[:5])
            if result.warning_messages:
                result_lines.append("注意:")
                result_lines.extend(f"- {message}" for message in result.warning_messages[:5])
            else:
                result_lines.append("エラー: なし")

            await _safe_send_ephemeral(interaction, "\n".join(result_lines))
            await send_log(
                self.bot,
                content=(
                    f"[estimate->task] user={interaction.user} event={record.event_name} work={record.work_title}\n"
                    + "\n".join(result_lines)
                )[:1900],
            )
        except Exception as exc:
            self.is_processing = False
            print(f"estimate->task post process failed: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            await _safe_send_ephemeral(interaction, f"task 化は実行されましたが、結果表示の更新でエラーが発生しました: {exc}")



def register_estimate_command(
    bot: commands.Bot,
    openai_client: Any | None = None,
    task_runtime_options: dict[str, Any] | None = None,
) -> None:
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
            ai_outcome = await asyncio.to_thread(
                request_estimate_adjustment,
                openai_client=openai_client,
                event_name=resolved_event_name,
                work_title=work_title,
                work_category=work_category.value,
                work_type=work_type.value,
                difficulty=difficulty.value if difficulty else None,
                due_date=parsed_due_date.isoformat(),
                template_steps=simple_result.steps,
                simple_total_hours=simple_result.total_hours,
                calendar_context=_build_ai_calendar_context(calendar_summary),
            )

            if ai_outcome.used_ai and ai_outcome.result:
                using_ai = True
                steps = ai_outcome.result.adjusted_steps
                total_hours = ai_outcome.result.total_hours
                commentary = _normalize_ai_commentary(ai_outcome.result.commentary, commentary)
                schedule_lines = _normalize_ai_schedule_lines(ai_outcome.result.schedule_plan, simple_result.schedule_lines)
                ai_note = _normalize_ai_note(ai_outcome.result.buffer_comment, using_ai=True)
            elif ai_outcome.failure_reason:
                ai_note = f"AI補正は使えませんでした: {_localize_ai_failure_reason(ai_outcome.failure_reason)}"

            if calendar_summary:
                commentary = _apply_calendar_pressure_to_commentary(
                    base_commentary=commentary,
                    all_day_count=calendar_summary.all_day_count,
                    semi_all_day_count=calendar_summary.semi_all_day_count,
                    light_count=calendar_summary.light_count,
                )

            estimate_created_at = save_latest_estimate(
                user_id=str(interaction.user.id),
                event_name=resolved_event_name,
                work_title=work_title,
                due_date=due_date,
                work_category=work_category.value,
                work_type=work_type.value,
            )
            save_estimate_snapshot(
                user_id=str(interaction.user.id),
                event_name=resolved_event_name,
                work_title=work_title,
                due_date=due_date,
                work_category=work_category.value,
                work_type=work_type.value,
                steps=steps,
                estimate_created_at=estimate_created_at,
            )

            stage = "display"
            step_lines = "\n".join(f"- {step['step_name']}: {step['hours']:.1f}h" for step in steps)
            embed = build_estimate_embed(
                event_name=resolved_event_name,
                work_title=work_title,
                work_category=work_category.value,
                work_type=work_type.value,
                work_type_weight=simple_result.work_type_weight,
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
            view = EstimateTaskActionView(
                bot=bot,
                owner_user_id=str(interaction.user.id),
                estimate_created_at=estimate_created_at,
                openai_client=openai_client,
                task_runtime_options=task_runtime_options,
            )
            await interaction.followup.send(embed=embed, view=view)
            await send_log(
                bot,
                content=f"[estimate] user={interaction.user} event={resolved_event_name} work={work_title}",
                embed=embed,
            )
        except ValueError:
            if stage == "date_parse":
                await interaction.followup.send("日付形式が正しくありません。形式: YYYY-MM-DD（例: 2026-05-20）")
                return
            print(f"estimate error at {stage}: ValueError")
            await interaction.followup.send("見積処理中に入力値の解釈でエラーが発生しました。内容を確認して再実行してください。")
        except Exception as exc:
            print(f"estimate error at {stage}: {type(exc).__name__}: {exc}")
            await interaction.followup.send(f"見積処理中にエラーが発生しました。失敗段階: {stage}")
