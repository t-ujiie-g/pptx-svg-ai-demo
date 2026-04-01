# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

スライド作成に特化したAIエージェントアプリ。チャットベースのUIでプレゼンテーション（PPTX）を自動生成する。

## Tech Stack

- **Backend**: Python 3.13 + FastAPI + Google ADK (Agent Development Kit) + VertexAI Gemini
- **Frontend**: React 19 + TypeScript + Vite
- **PPTX生成**: PptxGenJS (Node.js) をバックエンドから実行

## Commands

```bash
# Docker Compose で全サービス起動（推奨）
make dev

# 個別コンテナ操作
make up       # バックグラウンド起動
make down     # 停止
make logs     # ログ確認
make clean    # 全クリーンアップ

# ローカル開発（Dockerなし）
make install-backend   # backend/.venv 作成
make install-frontend  # node_modules インストール
make run-backend       # uvicorn 起動 (port 8000)
make run-frontend      # vite dev (port 3000)

# Lint & Test
make lint    # ruff (backend) + eslint (frontend)
make test    # pytest (backend) + npm test (frontend)

# ヘルスチェック
make health  # curl localhost:8000/health
```

## Architecture

```
Frontend (React) :3000
    │ REST API + SSE
    ▼
Backend (FastAPI + Google ADK) :8000
    │ root_coordinator agent
    │   └── pptx_agent
    │       ├── PptxGenJS (Node.js) でPPTX生成
    │       └── ADK SkillToolset (スキルベースのスライド作成)
    │
    ├── Google Search Tool
    ├── Artifact Store (生成ファイルの一時保存)
    └── File Bridge (添付ファイルの受け渡し)
```

### Key Design Decisions

1. **PPTX生成**: PptxGenJS をNode.jsスクリプトとしてバックエンドから `subprocess.run` で実行。生成されたファイルはArtifact Storeに保存し、フロントエンドからダウンロード可能

2. **Agent Architecture**: Google ADK の `LlmAgent` を使用。root_coordinator が pptx_agent にスライド作成タスクを委譲

3. **SSEストリーミング**: チャットレスポンスはServer-Sent Eventsでリアルタイム配信。ツール実行状況やPPTXアーティファクト生成もSSEイベントで通知

4. **スライドプレビュー**: フロントエンドでPPTXファイルをSVGに変換してプレビュー表示

## Key Files

### Backend
- `backend/src/config.py` - 設定管理
- `backend/src/constants.py` - 定数
- `backend/src/main.py` - FastAPIエントリーポイント
- `backend/src/agents/root_agent.py` - ルートエージェント
- `backend/src/agents/pptx_agent.py` - PPTXエージェント（PptxGenJS実行）
- `backend/src/api/chat.py` - チャットAPI（SSEストリーミング）
- `backend/src/api/artifacts.py` - アーティファクトダウンロードAPI
- `backend/src/api/prompts.py` - プロンプトテンプレート生成API
- `backend/src/api/health.py` - ヘルスチェック
- `backend/src/services/artifact_store.py` - アーティファクト保存
- `backend/src/agents/tools/file_bridge.py` - 添付ファイル管理

### Frontend
- `frontend/src/App.tsx` - アプリルート
- `frontend/src/config.ts` - 設定
- `frontend/src/components/ChatLayout.tsx` - レイアウト管理
- `frontend/src/components/ChatView.tsx` - チャットUI
- `frontend/src/components/ChatMessageList.tsx` - メッセージ一覧
- `frontend/src/components/PptxPanel.tsx` - PPTXプレビューパネル
- `frontend/src/components/PptxSlideViewer.tsx` - スライドビューア
- `frontend/src/components/Sidebar.tsx` - サイドバー
- `frontend/src/hooks/useChat.ts` - チャットロジック
- `frontend/src/services/chatHistory.ts` - チャット履歴管理

## Environment Setup

1. `gcloud auth application-default login` で Google Cloud 認証
2. `cp .env.example .env` で環境変数設定
3. 必須環境変数: `GOOGLE_CLOUD_PROJECT`
