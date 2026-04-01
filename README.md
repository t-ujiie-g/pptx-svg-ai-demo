# スライド作成AI

チャットベースのUIでプレゼンテーション（PPTX）を自動生成するAIエージェントアプリです。

## 主な機能

- AIとの対話でスライドを自動生成（PptxGenJS + react-icons によるリッチなデザイン）
- 生成されたPPTXをブラウザ上でSVGプレビュー
- フロントエンドでの簡易編集（シェイプの移動・リサイズ、テキスト編集、塗りつぶし色変更）
- 編集後のPPTXエクスポート
- ファイル添付対応（画像・PDF等をAIに読み込ませて参考にできる）
- プロンプトテンプレート機能

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| バックエンド | Python 3.13 + FastAPI + Google ADK + Vertex AI Gemini |
| フロントエンド | React 19 + TypeScript + Vite |
| PPTX生成 | PptxGenJS (Node.js) をバックエンドから subprocess 実行 |
| スライドプレビュー・編集 | pptx-svg（PPTX↔SVG変換 + シェイプ編集API、Wasm） |
| アイコン | react-icons + sharp（SVG→PNG変換してスライドに埋め込み） |

## セットアップ

### 事前準備

1. **Google Cloud** — プロジェクト作成 + Vertex AI API 有効化
2. **認証** — `gcloud auth application-default login`

### 環境変数

```bash
cp .env.example .env
# .env を編集
```

| 変数 | 説明 | 必須 |
|------|------|:----:|
| `GOOGLE_CLOUD_PROJECT` | GCPプロジェクトID | ○ |
| `GOOGLE_CLOUD_LOCATION` | ロケーション（デフォルト: `global`） | |
| `VITE_API_BASE_URL` | バックエンドURL（デフォルト: `http://localhost:8000`） | |

### 起動

```bash
# Docker Compose で起動（推奨）
make dev

# バックグラウンド起動
make up

# 停止
make down

# ログ確認
make logs
```

### ローカル開発（Dockerなし）

```bash
make install-backend   # backend/.venv 作成 + npm パッケージ
make install-frontend  # node_modules インストール
make run-backend       # uvicorn (port 8000)
make run-frontend      # vite dev (port 3000)
```

### 動作確認

| サービス | URL |
|---------|-----|
| フロントエンド | http://localhost:3000 |
| バックエンド API | http://localhost:8000 |
| ヘルスチェック | http://localhost:8000/health |

## アーキテクチャ

```
Frontend (React + pptx-svg) :3000
    │ REST API + SSE
    ▼
Backend (FastAPI + Google ADK) :8000
    │ root_coordinator agent
    │   └── pptx_agent
    │       ├── PptxGenJS (Node.js) でPPTX生成
    │       └── ADK SkillToolset (スキルベースのスライド作成)
    │
    ├── Google Search Tool（Web検索）
    ├── Artifact Store（生成ファイルの一時保存）
    └── File Bridge（添付ファイルの受け渡し）
```

### 設計方針

1. **PPTX生成**: PptxGenJS を Node.js スクリプトとしてバックエンドから `subprocess.run` で実行。react-icons + sharp でアイコンをPNG化してスライドに埋め込み。生成ファイルは Artifact Store に保存
2. **エージェント構成**: Google ADK の `LlmAgent` を使用。root_coordinator → pptx_agent の2層構成
3. **SSEストリーミング**: チャットレスポンスは Server-Sent Events でリアルタイム配信。PPTX生成完了もSSEイベントで通知
4. **スライドプレビュー・編集**: pptx-svg ライブラリ（Wasm）でPPTXをSVGに変換してプレビュー。クリックでシェイプ選択、ドラッグで移動・リサイズ、テキスト・塗りつぶし色の編集が可能。編集後のPPTXエクスポートにも対応

## ディレクトリ構成

```
pptx-svg-ai-demo/
├── docker-compose.yml
├── .env.example
├── Makefile
├── CLAUDE.md
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── skills/                    # ADK スキル定義
│   └── src/
│       ├── main.py                # FastAPI エントリポイント
│       ├── config.py              # 設定管理
│       ├── constants.py           # 定数
│       ├── agents/
│       │   ├── root_agent.py      # ルートエージェント
│       │   ├── pptx_agent.py      # PPTXエージェント（PptxGenJS実行）
│       │   └── tools/
│       │       └── file_bridge.py # 添付ファイル管理
│       ├── api/
│       │   ├── chat.py            # チャットAPI（SSEストリーミング）
│       │   ├── artifacts.py       # アーティファクトダウンロードAPI
│       │   ├── prompts.py         # プロンプトテンプレート生成API
│       │   └── health.py          # ヘルスチェック
│       └── services/
│           └── artifact_store.py  # アーティファクト保存
│
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── App.tsx                # アプリルート
        ├── config.ts              # 設定
        ├── components/
        │   ├── ChatLayout.tsx     # レイアウト管理
        │   ├── ChatView.tsx       # チャットUI
        │   ├── ChatMessageList.tsx # メッセージ一覧
        │   ├── PptxPanel.tsx      # PPTXプレビューパネル
        │   ├── PptxSlideViewer.tsx # スライドビューア（編集機能付き）
        │   ├── PptxEditToolbar.tsx # 編集ツールバー（塗りつぶし・テキスト）
        │   └── Sidebar.tsx        # サイドバー
        ├── hooks/
        │   ├── useChat.ts         # チャットロジック
        │   ├── usePptxRenderer.ts # PptxRenderer ライフサイクル管理
        │   └── usePptxDrag.ts     # ドラッグ移動・リサイズ操作
        ├── utils/
        │   └── pptxSvg.ts         # SVG DOM操作ユーティリティ
        └── services/
            ├── chatHistory.ts     # チャット履歴管理（localStorage）
            └── savedPrompts.ts    # プロンプトテンプレート保存
```
