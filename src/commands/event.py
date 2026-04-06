import discord
from discord.ext import commands

from src.services.db_service import get_current_event, set_current_event


def register_event_command(bot: commands.Bot) -> None:
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

            await interaction.followup.send(
                f"現在のイベントを「{saved_event}」に設定しました。",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ イベント設定に失敗しました: {str(e)}",
                ephemeral=True,
            )
