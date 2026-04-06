import discord
from discord.ext import commands

from src.services.db_service import get_current_event, set_current_event
from src.services.notion_service import EVENT_PROPERTY_NAME, ensure_select_option


def register_event_command(bot: commands.Bot, notion, notion_db_id: str | None) -> None:
    @bot.tree.command(name="event", description="現在のイベントを設定")
    async def set_event(
        interaction: discord.Interaction,
        event_name: str,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            user_id = str(interaction.user.id)
            set_current_event(user_id, event_name)

            saved_event = get_current_event(user_id)
            if saved_event != event_name:
                raise RuntimeError("イベント設定の保存結果を確認できませんでした。")

            notice_lines = [f"現在のイベントを「{saved_event}」に設定しました。"]

            if not notion_db_id:
                notice_lines.append("⚠️ Notion DB ID が未設定のため、Notion 候補同期はスキップしました。")
            else:
                try:
                    sync_result = ensure_select_option(
                        notion=notion,
                        database_id=notion_db_id,
                        property_name=EVENT_PROPERTY_NAME,
                        option_name=event_name,
                    )
                    if sync_result == "added":
                        notice_lines.append("Notion のイベント候補にも追加しました。")
                    else:
                        notice_lines.append("Notion のイベント候補には既に存在しています。")
                except Exception as notion_error:
                    notice_lines.append(
                        f"⚠️ current_event の保存は成功しましたが、Notion候補追加は失敗しました: {str(notion_error)}"
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
