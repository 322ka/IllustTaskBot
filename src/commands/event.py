import os
import traceback

import discord
from discord.ext import commands

from src.services.db_service import get_current_event, set_current_event
from src.services.notion_service import (
    EVENT_PROPERTY_NAME,
    ensure_event_page_with_details,
    ensure_select_option,
)


def register_event_command(
    bot: commands.Bot,
    notion,
    notion_db_id: str | None,
    event_database_id: str | None,
) -> None:
    @bot.tree.command(name="event", description="現在のイベントを設定")
    async def set_event(
        interaction: discord.Interaction,
        event_name: str,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            user_id = str(interaction.user.id)
            previous_event = get_current_event(user_id)
            set_current_event(user_id, event_name)

            saved_event = get_current_event(user_id)
            if saved_event != event_name:
                raise RuntimeError("イベント設定の保存結果を確認できませんでした。")

            if previous_event == event_name:
                notice_lines = [f"現在のイベントはすでに「{saved_event}」です。"]
            else:
                notice_lines = [f"現在のイベントを「{saved_event}」に設定しました。"]

            resolved_notion_db_id = notion_db_id or os.getenv("NOTION_DATABASE_ID")
            resolved_event_database_id = event_database_id or os.getenv("NOTION_EVENT_DATABASE_ID")

            if not resolved_notion_db_id:
                notice_lines.append(
                    "⚠️ SCHEDULE同期: NOTION_DATABASE_ID が未設定のため、"
                    "イベント候補同期はスキップしました。"
                )
            else:
                try:
                    sync_result = ensure_select_option(
                        notion=notion,
                        database_id=resolved_notion_db_id,
                        property_name=EVENT_PROPERTY_NAME,
                        option_name=event_name,
                    )
                    if sync_result == "added":
                        notice_lines.append("SCHEDULE同期: イベント候補を追加しました。")
                    else:
                        notice_lines.append("SCHEDULE同期: イベント候補は既に存在しています。")
                except Exception as notion_error:
                    traceback.print_exc()
                    notice_lines.append(
                        "⚠️ SCHEDULE同期に失敗しました: "
                        f"{type(notion_error).__name__}: {str(notion_error)}"
                    )

            if resolved_event_database_id:
                try:
                    page_result, title_property_name = ensure_event_page_with_details(
                        notion=notion,
                        database_id=resolved_event_database_id,
                        event_name=event_name,
                    )
                    if page_result == "created":
                        notice_lines.append(
                            "EVENT DB同期: 新規ページを作成しました。"
                            f" (title: {title_property_name})"
                        )
                    else:
                        notice_lines.append(
                            "EVENT DB同期: 既に同名イベントがあります。"
                            f" (title: {title_property_name})"
                        )
                except Exception as event_db_error:
                    traceback.print_exc()
                    notice_lines.append(
                        "⚠️ EVENT DB同期に失敗しました: "
                        f"{type(event_db_error).__name__}: {str(event_db_error)}"
                    )
            else:
                notice_lines.append(
                    "⚠️ EVENT DB同期: NOTION_EVENT_DATABASE_ID が未設定のため、"
                    "EVENT DB へのページ作成をスキップしました。"
                )

            await interaction.followup.send(
                "\n".join(notice_lines),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ イベント設定に失敗しました: {str(e)}",
                ephemeral=True,
            )
