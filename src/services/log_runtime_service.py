from __future__ import annotations

import traceback
from typing import Any


async def send_log(bot: Any, content: str | None = None, embed: Any | None = None) -> None:
    try:
        log_channel_id = getattr(bot, "log_channel_id", 0) or 0
        if not log_channel_id:
            return

        channel = bot.get_channel(log_channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(log_channel_id)
            except Exception as exc:
                print(
                    f"log_service: LOG_CHANNEL_ID {log_channel_id} のチャンネル取得に失敗しました: "
                    f"{type(exc).__name__}: {exc}"
                )
                return

        if channel is None:
            print(f"log_service: LOG_CHANNEL_ID {log_channel_id} のチャンネルが見つかりません。")
            return

        if content is None and embed is None:
            return

        await channel.send(content=content, embed=embed)
    except Exception as exc:
        print(f"log_service: failed to send log: {type(exc).__name__}: {exc}")
        traceback.print_exc()
