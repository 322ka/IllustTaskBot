# IllustTask Bot 🎨

イラストレーター向けの Discord × AI × Notion 自動タスク管理システム

## 🎯 機能

- **自動タスク分解**: 納期から逆算して 11 ステップのワークフローを自動生成
- **AI スケジュール分析**: 毎朝 9 時に今週のタスク分析を Discord に投稿
- **モバイル対応**: Discord Mobile で いつでもどこでもタスク追加

## 🚀 セットアップ

### 1. トークン取得

- **Discord Bot Token**: https://discord.com/developers/applications
- **OpenAI API Key**: https://platform.openai.com/api-keys
- **Notion API Token**: https://www.notion.so/my-integrations

### 2. リポジトリクローン

```bash
git clone https://github.com/your_username/IllustTaskBot.git
cd IllustTaskBot
```

## /estimate メモ

### 入力項目

- `作品名`
- `締切日`
- `作業種別`
- `作品種別`
- `難易度` 任意
- `イベント名` 任意

### 挙動

- まずテンプレ工程と固定時間で簡易見積を作成します
- AI が使える場合は、その簡易見積をもとに難易度補正、バッファ考慮、簡易スケジュール案を返します
- AI が失敗した場合でも、簡易見積を fallback として返します
- `/estimate` はまだ Notion 保存を行いません

### 必要な環境変数

- `DISCORD_TOKEN`
- `OPENAI_API_KEY`
- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`
- `NOTION_EVENT_DATABASE_ID`
- `NOTION_FANFIC_DATABASE_ID`
