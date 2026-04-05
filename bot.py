# bot.py
import discord
from discord.ext import commands, tasks
from openai import OpenAI
from notion_client import Client
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import json

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_DB_ID = '88a15e851b9e40c8a488d9d58cc5931c'
REPORT_CHANNEL_ID = int(os.getenv('REPORT_CHANNEL_ID', '0'))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
notion = Client(auth=NOTION_TOKEN)

WORKFLOW_STEPS = [
    "情報収集", "イメージ策定", "大ラフ", "詳細ラフ", 
    "カラーラフ", "下書き", "線画", "色分け", "着彩", "修正", "仕上げ"
]

@bot.event
async def on_ready():
    print(f'{bot.user} がログインしました')
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンド {len(synced)} 個を同期しました")
    except Exception as e:
        print(e)
    daily_report.start()

@bot.tree.command(name="task", description="新しいイラストプロジェクトを追加")
async def add_task(
    interaction: discord.Interaction,
    プロジェクト名: str,
    締切日: str,
    種類: str = "依頼"
):
    await interaction.response.defer()
    
    try:
        try:
            deadline = datetime.strptime(締切日, "%Y-%m-%d")
        except ValueError:
            await interaction.followup.send(
                "❌ 日付形式が正しくありません。\n形式: YYYY-MM-DD（例：2025-03-15）"
            )
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

【出力形式】JSON配列のみ（説明文は不要）
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
            temperature=0.7
        )
        
        response_text = response.choices[0].message.content
        
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        tasks_list = json.loads(response_text.strip())
        
        created_count = 0
        for task in tasks_list:
            try:
                notion.pages.create(
                    parent={"database_id": NOTION_DB_ID},
                    properties={
                        "タイトル": {
                            "title": [{"text": {"content": f"{task['task_name']}"}}]
                        },
                        "プロジェクト": {
                            "rich_text": [{"text": {"content": プロジェクト名}}]
                        },
                        "締切": {
                            "date": {"start": task["deadline"]}
                        },
                        "種類": {
                            "select": {"name": 種類}
                        },
                        "進捗": {
                            "select": {"name": "未開始"}
                        }
                    }
                )
                created_count += 1
            except Exception as e:
                print(f"Notion エラー: {e}")
                continue
        
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
        
        await interaction.followup.send(embed=embed)
        
    except json.JSONDecodeError as e:
        await interaction.followup.send(f"❌ AI の応答をパースできませんでした\n{str(e)}")
    except Exception as e:
        await interaction.followup.send(f"❌ エラー: {str(e)}")

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
