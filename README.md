# スライド作成AI (pptx-svg demo)

チャットベースのUIでプレゼンテーション（PPTX）を **新規生成 / 既存編集** できる AI エージェントのデモアプリです。
[pptx-svg](https://zenn.dev/t_ujiie/articles/49a07be07eaeb7) を土台に、AIと人間が同じスライドを共同編集できるワークベンチを目指しています。

## 主な機能

- チャットでの指示による PPTX の **新規生成**（PptxGenJS + react-icons）
- 既存 PPTX を添付しての **編集依頼**（python-pptx）
- 生成・編集結果をブラウザ上で **SVG プレビュー**（pptx-svg / Wasm）
- プレビュー上でのシェイプ **移動・リサイズ・テキスト編集・塗りつぶし色変更**
- 編集後 PPTX の **ダウンロード**
- 編集後の状態を **AI に戻して追加指示** できるループ
- ファイル添付（画像・PDF・PPTX 等）
- プロンプトテンプレート機能

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| バックエンド | Python 3.13 + FastAPI + Google ADK + Gemini (Vertex AI / Gemini API 両対応) |
| フロントエンド | React 19 + TypeScript + Vite |
| PPTX 新規生成 | PptxGenJS (Node.js を subprocess 実行) |
| PPTX 編集 | python-pptx |
| プレビュー・編集UI | pptx-svg（PPTX ↔ SVG 変換、Wasm） |
| アイコン | react-icons + sharp（SVG→PNG 化） |

PPTX 関連の処理は [Anthropic の Claude Skills の pptx skill](https://github.com/anthropics/skills/tree/main/skills/pptx) をベースに、編集部分を python-pptx に差し替えるなどの改変を加えています。

## アーキテクチャ

```
Frontend (React + pptx-svg(Wasm)) :3000
    │ REST API + SSE
    ▼
Backend (FastAPI + Google ADK) :8000
    │ root_coordinator agent
    │   └── pptx_agent
    │       └── ADK SkillToolset
    │           └── pptx skill
    │               ├── generate_pptx.py … PptxGenJS で新規作成
    │               └── edit_pptx.py     … python-pptx で既存編集
    │
    ├── Google Search Tool
    ├── Artifact Store（生成ファイルの一時保存）
    └── File Bridge（添付ファイルの受け渡し）
```

## セットアップ

### 1. 前提ツール

- Docker / Docker Compose（推奨起動方法）
- ローカル開発する場合は Python 3.13 / Node.js 20+ / npm

### 2. Gemini バックエンドの選択

このアプリは **Vertex AI** と **Gemini API (AI Studio)** のどちらでも動きます。環境変数 `GOOGLE_GENAI_USE_VERTEXAI` で切り替えます。

#### A. Gemini API (AI Studio) を使う（個人で試すならこちらが簡単）

1. https://aistudio.google.com/app/apikey で API Key を発行
2. `.env` に API Key を設定（後述）

#### B. Vertex AI を使う

1. GCP プロジェクトを用意し、Vertex AI API を有効化
2. 認証:
   ```bash
   gcloud auth application-default login
   ```
3. `.env` にプロジェクト ID を設定（後述）

### 3. 環境変数

```bash
cp .env.example .env
# .env を編集
```

| 変数 | 説明 | 必須 |
|------|------|:----:|
| `GOOGLE_GENAI_USE_VERTEXAI` | `FALSE`=Gemini API / `TRUE`=Vertex AI | ○ |
| `GOOGLE_API_KEY` | Gemini API 利用時の API Key | A のとき |
| `GOOGLE_CLOUD_PROJECT` | GCP プロジェクトID | B のとき |
| `GOOGLE_CLOUD_LOCATION` | ロケーション（デフォルト `global`） | |
| `GENAI_MODEL` | root エージェントのモデル | |
| `PPTX_AGENT_MODEL` | pptx エージェントのモデル | |
| `VITE_API_BASE_URL` | バックエンドURL（デフォルト `http://localhost:8000`） | |

## 起動方法

### Docker Compose（推奨）

```bash
# 初回 or 変更があるとき: ビルドしつつフォアグラウンド起動
make dev

# バックグラウンド起動
make up

# 停止
make down

# ログ確認
make logs

# 全クリーンアップ（コンテナ・ボリューム・イメージ・.venv/node_modules）
make clean
```

Vertex AI を使う場合、ホスト側の `~/.config/gcloud` が backend コンテナにマウントされるので、事前に `gcloud auth application-default login` を済ませておけば追加設定は不要です。

### ローカル開発（Docker を使わない）

```bash
# 依存インストール
make install-backend   # backend/.venv 作成 + グローバルな npm パッケージ導入
make install-frontend  # frontend/node_modules 導入

# 別ターミナルでそれぞれ起動
make run-backend   # uvicorn (port 8000, --reload)
make run-frontend  # vite dev server (port 3000)
```

`make install-backend` は `backend/` で venv を作り、`pip install -e .` したのち PptxGenJS 実行に必要な `pptxgenjs / react / react-dom / react-icons / sharp` をグローバルに `npm install -g` します。権限の問題で失敗する場合は `sudo` を付けるか、nvm/volta 等で Node.js を user-local にインストールしてください。

### 動作確認

| サービス | URL |
|---------|-----|
| フロントエンド | http://localhost:3000 |
| バックエンド API | http://localhost:8000 |
| ヘルスチェック | http://localhost:8000/health（`make health` でも可） |

起動後、フロントエンドにアクセスして以下を試せます。

1. チャット欄に「新製品紹介のスライドを5枚で作って」などと入力 → 新規生成
2. 既存 `.pptx` を添付して「このスライドの表紙を英語にして」などと指示 → 既存編集
3. プレビューに表示されたシェイプをクリック → ドラッグで移動・リサイズ、ツールバーから色・テキスト変更
4. 編集を加えた状態で追加のチャット指示 → AI が編集後の状態から続きを処理
5. エクスポートボタンで編集後 PPTX をダウンロード

## 開発 Tips

### Lint / Test

```bash
make lint    # ruff (backend) + eslint (frontend)
make test    # pytest (backend) + npm test (frontend)
```

### ホットリロード

- Docker Compose 起動時も `backend/src` と `frontend/src` をコンテナにマウントしているため、ソース変更は自動反映されます
- 依存（`pyproject.toml` / `package.json` / `backend/skills` の変更）は再ビルドが必要なので `make dev` で起動し直してください

### Skills の編集

PPTX 関連のスクリプトは `backend/skills/pptx/` 以下にあります。

- `scripts/generate_pptx.py` … PptxGenJS を使った新規生成ラッパ
- `scripts/edit_pptx.py` … python-pptx を使った ops ベース編集
- `SKILL.md` … AIエージェントに渡されるスキル定義（プロンプト）

スキル側を変更した場合、Docker Compose では `backend/skills` が ro マウントされているので再起動だけで反映されます。

### トラブルシュート

- **`GOOGLE_API_KEY` が未設定のエラー** → `GOOGLE_GENAI_USE_VERTEXAI=FALSE` のまま API Key を入れ忘れていないか確認
- **Vertex AI の認証エラー** → `gcloud auth application-default login` を再実行し、`~/.config/gcloud` がマウントされているか確認
- **PPTX 生成が空になる / スクリプトエラー** → `make logs` で backend ログを確認。`generate_pptx.py` は Node.js の実行結果を stderr に出します
- **port 3000 / 8000 が衝突** → 既存プロセスを止めるか `.env` と `docker-compose.yml` の port 指定を変更

## ディレクトリ構成

```
pptx-svg-ai-demo/
├── docker-compose.yml
├── .env.example
├── Makefile
├── CLAUDE.md
├── docs/
│   └── demo-article.md        # 紹介記事
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── skills/
│   │   └── pptx/              # Anthropic Skills をベースに改変した pptx skill
│   │       ├── SKILL.md
│   │       ├── scripts/
│   │       │   ├── generate_pptx.py   # PptxGenJS 経由で新規生成
│   │       │   ├── edit_pptx.py       # python-pptx で編集
│   │       │   └── pptx_inspect.js
│   │       └── references/
│   └── src/
│       ├── main.py                # FastAPI エントリポイント
│       ├── config.py              # 設定管理（Vertex/Gemini API 両対応）
│       ├── constants.py
│       ├── agents/
│       │   ├── root_agent.py      # ルートエージェント
│       │   ├── pptx_agent.py      # PPTXエージェント（Skill 呼び出し）
│       │   └── tools/
│       │       └── file_bridge.py # 添付ファイル管理
│       ├── api/
│       │   ├── chat.py            # チャットAPI（SSE）
│       │   ├── artifacts.py       # アーティファクトAPI（GET/PUT）
│       │   ├── prompts.py         # プロンプトテンプレート生成API
│       │   └── health.py
│       └── services/
│           └── artifact_store.py
│
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── App.tsx
        ├── config.ts
        ├── components/
        │   ├── ChatLayout.tsx
        │   ├── ChatView.tsx
        │   ├── ChatMessageList.tsx
        │   ├── PptxPanel.tsx
        │   ├── PptxSlideViewer.tsx   # 編集機能付きビューア
        │   ├── PptxEditToolbar.tsx
        │   └── Sidebar.tsx
        ├── hooks/
        │   ├── useChat.ts
        │   ├── usePptxRenderer.ts
        │   ├── usePptxDrag.ts
        │   └── useFileAttachment.ts
        ├── utils/
        │   └── pptxSvg.ts
        └── services/
            ├── chatHistory.ts
            └── savedPrompts.ts
```
