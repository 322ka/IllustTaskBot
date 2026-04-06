from __future__ import annotations

import json
import os
import traceback
from datetime import datetime
from typing import Any, Callable

import discord
from discord.ext import commands

from src.services.db_service import get_current_event
from src.services.notion_service import ensure_fanfic_page, ensure_select_option


EVENT_REQUIRED_MESSAGE = (
    "イベント名が指定されていません。先に /event で設定するか、"
    "/task に event_name を指定してください。"
)


def resolve_event_name(explicit_event_name: str | None, user_id: str) -> str | None:
    if explicit_event_name:
        return explicit_event_name

    return get_current_event(user_id)


def register_task_command(
    bot: commands.Bot,
    openai_client: Any,
    notion: Any,
    notion_db_id: str | None,
    fanfic_database_id: str | None,
    get_database_schema_config: Callable[[str], tuple[str, dict[str, set[str]]]],
    build_select_property: Callable[[str, str | None, dict[str, set[str]], list[str]], dict | None],
    notion_prop_schedule_date: str,
    notion_prop_category: str,
    notion_prop_event: str,
    notion_prop_work_title: str,
    notion_prop_done: str,
) -> None:
    @bot.tree.command(name="task", description="新しいイラストプロジェクトを追加")
    async def add_task(
        interaction: discord.Interaction,
        プロジェクト名: str,
        締切日: str,
        種類: str = "依頼",
        event_name: str | None = None,
    ):
        await interaction.response.defer()

        try:
            try:
                datetime.strptime(締切日, "%Y-%m-%d")
            except ValueError:
                await interaction.followup.send(
                    "❌ 日付形式が正しくありません。\n形式: YYYY-MM-DD（例：2025-03-15）"
                )
                return

            resolved_event_name = resolve_event_name(
                explicit_event_name=event_name,
                user_id=str(interaction.user.id),
            )
            if not resolved_event_name:
                await interaction.followup.send(EVENT_REQUIRED_MESSAGE)
                return

            prompt = f"""あなたはイラストレーターのプロジェクトマネージャーです。

【プロジェクト情報】
- プロジェクト名: {プロジェクト名}
- 最終締切: {締切日}
- 種類: {種類}

【ワークフロー（順序は固定）】
1. 情報収集
2. イメージ策定
3. 大ラフ
4. 詳細ラフ
5. カラーラフ
6. 下書き
7. 線画
8. 色分け
9. 着彩
10. 修正
11. 仕上げ

最終締切（仕上げ）が {締切日} になるように逆算してください。
各ステップは通常 1-2 日かかるものとします。
複雑なプロジェクトは時間を多めに見積もってください。

【重要な出力ルール】
- JSON配列のみを返してください
- 説明文・前置き・補足・コードブロックは禁止です
- ```json や ``` で囲まないでください
- 返答は配列の `[` から始めて `]` で終えてください

【出力形式】JSON配列のみ
[
  {{
    "step": 1,
    "task_name": "情報収集",
    "deadline": "YYYY-MM-DD",
    "description": "クライアント打ち合わせ、資料収集"
  }},
  ...全11ステップ
]
"""

            response = openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )

            response_text = response.choices[0].message.content
            print(f"🧠 AI raw response repr: {response_text!r}")

            if not response_text or not response_text.strip():
                raise ValueError("AI の応答が空でした。")

            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            cleaned_response_text = response_text.strip()
            print(f"🧠 AI cleaned response preview: {cleaned_response_text[:300]!r}")

            tasks_list = json.loads(cleaned_response_text)

            print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f"📋 プロジェクト: {プロジェクト名}")
            print(f"📅 最終締切: {締切日}")
            print(f"🎪 イベント名: {resolved_event_name}")
            print(f"📊 生成されたタスク数: {len(tasks_list)}")
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

            resolved_notion_db_id = notion_db_id or os.getenv("NOTION_DATABASE_ID")
            resolved_fanfic_database_id = fanfic_database_id or os.getenv("NOTION_FANFIC_DATABASE_ID")
            if not resolved_notion_db_id:
                raise ValueError("NOTION_DATABASE_ID が設定されていません。")

            title_property_name, select_options = get_database_schema_config(resolved_notion_db_id)
            print(f"🧩 Notion title property: {title_property_name}")

            created_count = 0
            warning_messages = []
            sync_messages = []

            try:
                work_title_sync_result = ensure_select_option(
                    notion=notion,
                    database_id=resolved_notion_db_id,
                    property_name=notion_prop_work_title,
                    option_name=プロジェクト名,
                )
                select_options.setdefault(notion_prop_work_title, set()).add(プロジェクト名)
                if work_title_sync_result == "added":
                    sync_messages.append("SCHEDULE同期: 作品タイトル候補を追加しました。")
            except Exception as schedule_work_title_error:
                warning_messages.append(
                    f"{notion_prop_work_title}: '{プロジェクト名}' の候補同期に失敗 ({schedule_work_title_error})"
                )

            try:
                event_sync_result = ensure_select_option(
                    notion=notion,
                    database_id=resolved_notion_db_id,
                    property_name=notion_prop_event,
                    option_name=resolved_event_name,
                )
                select_options.setdefault(notion_prop_event, set()).add(resolved_event_name)
                if event_sync_result == "added":
                    sync_messages.append("SCHEDULE同期: イベント候補を追加しました。")
            except Exception as schedule_event_error:
                warning_messages.append(
                    f"{notion_prop_event}: '{resolved_event_name}' の候補同期に失敗 ({schedule_event_error})"
                )

            if resolved_fanfic_database_id:
                try:
                    fanfic_event_sync_result = ensure_select_option(
                        notion=notion,
                        database_id=resolved_fanfic_database_id,
                        property_name="イベント",
                        option_name=resolved_event_name,
                    )
                    if fanfic_event_sync_result == "added":
                        sync_messages.append("FANFIC同期: イベント候補を追加しました。")

                    fanfic_category_sync_result = ensure_select_option(
                        notion=notion,
                        database_id=resolved_fanfic_database_id,
                        property_name="分類タグ",
                        option_name=種類,
                    )
                    if fanfic_category_sync_result == "added":
                        sync_messages.append("FANFIC同期: 分類タグ候補を追加しました。")

                    fanfic_result, fanfic_title_property_name, fanfic_warnings = ensure_fanfic_page(
                        notion=notion,
                        database_id=resolved_fanfic_database_id,
                        work_title=プロジェクト名,
                        event_name=resolved_event_name,
                        category_name=種類,
                    )
                    if fanfic_result == "created":
                        sync_messages.append(
                            f"FANFIC同期: 作品ページを作成しました。 (title: {fanfic_title_property_name})"
                        )
                    else:
                        sync_messages.append(
                            f"FANFIC同期: 既に同名作品があります。 (title: {fanfic_title_property_name})"
                        )
                    warning_messages.extend(fanfic_warnings)
                except Exception as fanfic_error:
                    warning_messages.append(f"FANFIC同期に失敗: {fanfic_error}")
            else:
                sync_messages.append("FANFIC同期: NOTION_FANFIC_DATABASE_ID 未設定のためスキップしました。")

            for task in tasks_list:
                try:
                    print(f"⏳ タスク作成中: {task['task_name']} → {task['deadline']}")

                    properties = {
                        title_property_name: {
                            "title": [{"text": {"content": f"{resolved_event_name}：{task['task_name']}"}}]
                        },
                        notion_prop_schedule_date: {
                            "date": {"start": task["deadline"]}
                        },
                        notion_prop_done: {
                            "checkbox": False
                        }
                    }

                    category_prop = build_select_property(
                        notion_prop_category, 種類, select_options, warning_messages
                    )
                    if category_prop:
                        properties[notion_prop_category] = category_prop

                    work_title_prop = build_select_property(
                        notion_prop_work_title, プロジェクト名, select_options, warning_messages
                    )
                    if work_title_prop:
                        properties[notion_prop_work_title] = work_title_prop

                    event_prop = build_select_property(
                        notion_prop_event, resolved_event_name, select_options, warning_messages
                    )
                    if event_prop:
                        properties[notion_prop_event] = event_prop

                    notion.pages.create(
                        parent={"database_id": resolved_notion_db_id},
                        properties=properties
                    )

                    created_count += 1
                    print(f"   ✅ 作成成功: {task['task_name']}")

                except KeyError as e:
                    print(f"   ❌ キーエラー [{task.get('task_name', 'Unknown')}]: {str(e)}")
                    print(f"      タスク内容: {task}")
                    traceback.print_exc()
                    continue
                except Exception as e:
                    print(f"   ❌ Notion エラー [{task.get('task_name', 'Unknown')}]: {type(e).__name__}")
                    print(f"      詳細: {str(e)}")
                    traceback.print_exc()
                    continue

            print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f"📊 結果: {created_count}/{len(tasks_list)} 個作成成功")
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

            embed = discord.Embed(
                title="✅ プロジェクト自動分解完了！",
                description=f"**{プロジェクト名}** を {created_count} 個のタスクに分割しました",
                color=discord.Color.green()
            )

            task_text = "\n".join([
                f"**{t['task_name']}** → {t['deadline']}"
                for t in sorted(tasks_list, key=lambda x: x['deadline'])
            ])

            embed.add_field(
                name="📋 スケジュール",
                value=task_text[:1024],
                inline=False
            )

            if sync_messages:
                embed.add_field(
                    name="🔗 同期結果",
                    value="\n".join(f"- {message}" for message in sync_messages)[:1024],
                    inline=False,
                )

            if created_count != len(tasks_list):
                embed.add_field(
                    name="⚠️ 注意",
                    value=f"{len(tasks_list) - created_count} 個のタスク作成に失敗しました。\nコンソールを確認してください。",
                    inline=False
                )

            if warning_messages:
                unique_warnings = sorted(set(warning_messages))
                embed.add_field(
                    name="ℹ️ Notion設定との不一致",
                    value="\n".join(f"- {message}" for message in unique_warnings)[:1024],
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        except json.JSONDecodeError as e:
            print(f"❌ JSON パースエラー: {str(e)}")
            if 'response_text' in locals():
                print(f"🧠 AI response preview on parse error: {response_text[:500]!r}")
            await interaction.followup.send(f"❌ AI の応答をパースできませんでした\n{str(e)}")
        except Exception as e:
            print(f"❌ メインエラー: {type(e).__name__}")
            print(f"   詳細: {str(e)}")
            traceback.print_exc()
            await interaction.followup.send(f"❌ エラー: {str(e)}")
