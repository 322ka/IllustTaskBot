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

## Google Calendar \u9023\u643a\u30e1\u30e2

### \u6982\u8981

- Google \u30ab\u30ec\u30f3\u30c0\u30fc\u306f\u8aad\u307f\u53d6\u308a\u5c02\u7528\u3067\u9023\u643a\u3057\u307e\u3059
- \u66f8\u304d\u8fbc\u307f\u306f\u884c\u3044\u307e\u305b\u3093
- `/calendar_preview` \u3067\u6307\u5b9a\u671f\u9593\u306e\u4e88\u5b9a\u3092\u78ba\u8a8d\u3067\u304d\u307e\u3059
- `/estimate` \u3067\u306f\u4e88\u5b9a\u8003\u616e\u306e\u88dc\u8db3\u3092\u975e\u7834\u58ca\u3067\u8868\u793a\u3057\u307e\u3059

### \u5fc5\u8981\u306a\u8a2d\u5b9a

- `GOOGLE_TOKEN_FILE`
- `GOOGLE_CALENDAR_ID`
- `GOOGLE_CLIENT_SECRET_FILE`

### \u8a8d\u8a3c\u306b\u3064\u3044\u3066

- OAuth 2.0 \u306e authorized user token \u3092\u4f7f\u3044\u307e\u3059
- scope \u306f `https://www.googleapis.com/auth/calendar.readonly` \u306e\u307f\u3067\u3059
- token \u304c\u7121\u3044\u5834\u5408\u3067\u3082 bot \u5168\u4f53\u306f\u843d\u3061\u305a\u3001Google \u30ab\u30ec\u30f3\u30c0\u30fc\u9023\u643a\u3060\u3051\u30b9\u30ad\u30c3\u30d7\u3057\u307e\u3059
