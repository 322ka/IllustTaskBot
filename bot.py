import os
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from notion_client import Client
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

from src.commands.event import register_event_command
from src.commands.calendar_preview import register_calendar_preview_command
from src.commands.estimate_runtime import register_estimate_command
from src.commands.task import register_task_command
from src.services.db_service import init_db

init_db()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")
EVENT_DB_ID = os.getenv("NOTION_EVENT_DATABASE_ID")
FANFIC_DB_ID = os.getenv("NOTION_FANFIC_DATABASE_ID")
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
notion = Client(auth=NOTION_TOKEN)

WORKFLOW_STEPS = [
    "情報収集",
    "イメージ策定",
    "大ラフ",
    "詳細ラフ",
    "カラーラフ",
    "下書き",
    "線画",
    "色分け",
    "着彩",
    "修正",
    "仕上げ",
]

NOTION_PROP_SCHEDULE_DATE = "予定"
NOTION_PROP_WORK_PERIOD = "作業期間"
NOTION_PROP_CATEGORY = "カテゴリ"
NOTION_PROP_EVENT = "イベント名(進捗管理用)"
NOTION_PROP_WORK_TITLE = "作品タイトル名(進捗管理用)"
NOTION_PROP_DONE = "済"


def get_database_schema_config(database_id: str) -> tuple[str, dict[str, set[str]]]:
    """Notion DB の title プロパティ名と select オプション名を取得する。"""
    db = notion.databases.retrieve(database_id=database_id)
    title_property_name: str | None = None
    options_map: dict[str, set[str]] = {}

    for prop_name, prop in db.get("properties", {}).items():
        if prop.get("type") == "title":
            title_property_name = prop_name

        if prop.get("type") == "select":
            option_names = {
                opt.get("name")
                for opt in prop.get("select", {}).get("options", [])
                if opt.get("name")
            }
            options_map[prop_name] = option_names

    if not title_property_name:
        raise ValueError("Notion database に title プロパティが見つかりません。")

    return title_property_name, options_map


def build_select_property(
    property_name: str,
    value: str | None,
    select_options: dict[str, set[str]],
    warnings: list[str],
) -> dict | None:
    """select の値が存在する場合のみ Notion 用 property を返す。"""
    if not value:
        return None

    valid_values = select_options.get(property_name, set())
    if value not in valid_values:
        warnings.append(f"{property_name}: '{value}' は未登録のためスキップ")
        return None

    return {"select": {"name": value}}


register_event_command(
    bot=bot,
    notion=notion,
    notion_db_id=NOTION_DB_ID,
    event_database_id=EVENT_DB_ID,
    fanfic_database_id=FANFIC_DB_ID,
)
register_calendar_preview_command(bot=bot)
register_estimate_command(
    bot=bot,
    openai_client=openai_client,
    task_runtime_options={
        "notion": notion,
        "notion_db_id": NOTION_DB_ID,
        "fanfic_database_id": FANFIC_DB_ID,
        "get_database_schema_config": get_database_schema_config,
        "build_select_property": build_select_property,
        "notion_prop_schedule_date": NOTION_PROP_SCHEDULE_DATE,
        "notion_prop_category": NOTION_PROP_CATEGORY,
        "notion_prop_event": NOTION_PROP_EVENT,
        "notion_prop_work_title": NOTION_PROP_WORK_TITLE,
        "notion_prop_done": NOTION_PROP_DONE,
    },
)
register_task_command(
    bot=bot,
    openai_client=openai_client,
    notion=notion,
    notion_db_id=NOTION_DB_ID,
    fanfic_database_id=FANFIC_DB_ID,
    get_database_schema_config=get_database_schema_config,
    build_select_property=build_select_property,
    notion_prop_schedule_date=NOTION_PROP_SCHEDULE_DATE,
    notion_prop_category=NOTION_PROP_CATEGORY,
    notion_prop_event=NOTION_PROP_EVENT,
    notion_prop_work_title=NOTION_PROP_WORK_TITLE,
    notion_prop_done=NOTION_PROP_DONE,
)


@bot.event
async def on_ready():
    print(f"{bot.user} がログインしました")
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンド {len(synced)} 個を同期しました")
    except Exception as e:
        print(e)
    daily_report.start()


@tasks.loop(hours=24)
async def daily_report():
    channel = bot.get_channel(REPORT_CHANNEL_ID)
    if not channel:
        print("❌ レポートチャンネルが見つかりません")
        return

    try:
        today = datetime.now()
        week_end = today + timedelta(days=7)

        response = notion.databases.query(
            database_id=NOTION_DB_ID,
            filter={
                "and": [
                    {
                        "property": "締切",
                        "date": {"on_or_after": today.isoformat()}
                    },
                    {
                        "property": "締切",
                        "date": {"before": week_end.isoformat()}
                    }
                ]
            }
        )

        if not response['results']:
            embed = discord.Embed(
                title="📊 今週のタスク",
                description="今週のタスクはありません 🎉",
                color=discord.Color.blue()
            )
            await channel.send(embed=embed)
            return

        tasks_by_date = {}
        for page in response['results']:
            try:
                title = page['properties']['タイトル']['title'][0]['text']['content']
                deadline = page['properties']['締切']['date']['start']
                project = page['properties']['プロジェクト']['rich_text'][0]['text']['content']
                status = page['properties']['進捗']['select']['name']

                if deadline not in tasks_by_date:
                    tasks_by_date[deadline] = []

                tasks_by_date[deadline].append({
                    'title': title,
                    'project': project,
                    'status': status
                })
            except (KeyError, IndexError):
                continue

        sorted_dates = sorted(tasks_by_date.keys())

        tasks_text = ""
        for date in sorted_dates:
            tasks_text += f"\n**{date}**\n"
            for task in tasks_by_date[date]:
                status_emoji = {
                    "未開始": "⚪",
                    "進行中": "🟡",
                    "完了": "✅"
                }.get(task['status'], "⚪")
                tasks_text += f"  {status_emoji} {task['title']} ({task['project']})\n"

        analysis_prompt = f"""
今週のイラストプロジェクトのスケジュールを分析してください。

【タスク一覧】
{tasks_text}

以下の項目を分析してください：
1. 今週の総負荷（軽い・中程度・重い）
2. 締切が近い危険タスク（赤信号 🔴）
3. 優先度の高いプロジェクト
4. スケジュール調整の提案（あれば）

簡潔に、イラストレーター向けのアドバイスをしてください。
"""

        analysis_response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": analysis_prompt}],
            temperature=0.7
        )

        analysis_text = analysis_response.choices[0].message.content

        embed = discord.Embed(
            title="📊 今週のタスク分析",
            description=analysis_text,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        embed.add_field(
            name="📋 スケジュール",
            value=tasks_text[:1024],
            inline=False
        )

        embed.set_footer(text="毎朝 9時自動投稿")

        await channel.send(embed=embed)

    except Exception as e:
        print(f"レポートエラー: {e}")
        traceback.print_exc()
        await channel.send(f"❌ レポート生成エラー: {str(e)}")


@daily_report.before_loop
async def before_daily_report():
    await bot.wait_until_ready()
    now = datetime.now()
    target_time = now.replace(hour=9, minute=0, second=0)
    if now > target_time:
        target_time += timedelta(days=1)

    wait_seconds = (target_time - now).total_seconds()
    await discord.utils.sleep_until(target_time)


bot.run(DISCORD_TOKEN)
