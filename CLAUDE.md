# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

スライド作成に特化したAIエージェントアプリ。チャットベースのUIでプレゼンテーション (PPTX) を自動生成・編集する。
複数の評価フェーズ (style 抽出 / 情報保全 / Critic / リトライ + ペアワイズ) でLLMの再生成精度を担保している。

## Tech Stack

- **Backend**: Python 3.13 + FastAPI + Google ADK (Agent Development Kit) + VertexAI Gemini
- **Frontend**: React 19 + TypeScript + Vite
- **PPTX生成**: PptxGenJS (Node.js) + python-pptx (編集) を skill scripts として呼出
- **永続化**: バックエンド artifact_store (1h TTL) + フロント OPFS (チャット単位)

## Commands

```bash
# Docker Compose (推奨)
make dev      # 全サービス前面起動
make up       # バックグラウンド起動
make down     # 停止
make logs     # ログ確認
make clean    # 全クリーンアップ

# ローカル開発
make install-backend   # backend/.venv 作成
make install-frontend  # node_modules インストール
make run-backend       # uvicorn (port 8000)
make run-frontend      # vite (port 3000)

# Lint & Test
make lint    # ruff (backend) + eslint (frontend)
make test    # pytest (backend) + npm test (frontend)
make health  # curl localhost:8000/health
```

## Architecture (high-level)

```
Frontend (React) :3000
  ├── ChatLayout
  │     ├── Sidebar (sessions)
  │     ├── ChatView
  │     │     ├── ModeSelector       (intent / style_source 折り畳み)
  │     │     ├── PipelineProgress   (mode/style/preservation/critic/...)
  │     │     ├── ChatMessageList    (typing indicator + tool history)
  │     │     └── 入力欄 + ファイル添付 + style_ref 添付
  │     └── PptxPanel
  │           ├── PptxHistoryDropdown (OPFS世代)
  │           └── PptxSlideViewer (編集 + OPFSフォールバック)
  └── 永続化: localStorage (chat history) + OPFS (PPTX バイト)
        │ REST + SSE (multipart/form-data + text/event-stream)
        ▼
Backend (FastAPI + Google ADK) :8000
  ├── /chat/stream  (SSE): 大本のオーケストレーション
  │     ├── chat_request.parse_request    リクエスト解析
  │     ├── chat_pipeline.maybe_extract_style       Phase 2 (Layer A+B)
  │     ├── chat_pipeline.maybe_extract_target_entities  Phase 3 (pre-gen)
  │     ├── ADK Runner: agent v1 (root → pptx / search)
  │     ├── chat_pipeline.run_preservation_check    Phase 3 (post-gen)
  │     ├── chat_pipeline.run_critic_review          Phase 4
  │     └── (verdict=retry なら) Runner: agent v2
  │           ├── 再 preservation + critic
  │           ├── chat_pipeline.run_pairwise_compare Phase 4.5
  │           └── rollback (v1 が勝者なら v1 を再送)
  ├── /artifacts/{id}        : artifact_store (1h TTL)
  ├── /prompts/...           : テンプレート生成
  └── Agents
        ├── root_coordinator (ADK LlmAgent)
        ├── pptx_agent       (skill scripts: generate/edit/copy)
        └── search_agent     (Google Search builtin tool 単独)

Skill scripts (backend/skills/pptx/):
  ├── scripts/generate_pptx.py  PptxGenJS で新規作成
  ├── scripts/edit_pptx.py      python-pptx で編集 + テンプレコピー
  └── scripts/pptx_inspect.js   SVG → PNG + 構造抽出
```

### 評価フェーズ (LLM呼出順)

| Phase | 役割 | モデル tier (default) | 場所 |
|---|---|---|---|
| 1 | mode_spec 推定 (決定論) | (なし) | `agents/mode/inferrer.py` |
| 2 | スタイル抽出 (Layer A+B) | lite | `services/style_extractor.py` |
| 3 (pre) | 保全すべきエンティティ抽出 | lite | `services/entity_extractor.py` |
| - | エージェント実行 (root → pptx / search) | mid / high / mid | ADK Runner |
| 3 (post) | 出力エンティティ抽出 + 保全率計算 | lite + 決定論 | `services/preservation.py` |
| 4 | Critic 5軸評価 | mid | `services/critic.py` |
| 4.5 | リトライ → 再 critic → ペアワイズ → ロールバック | mid + mid | `services/critic.py` |

各フェーズは `feature_*` フラグで個別 OFF 可能 (`config.py`)。

## Key Files

### Backend
- `backend/src/config.py` — 設定 + 4階層 feature flag (style/preservation/critic/retry) + モデルtier解決
- `backend/src/constants.py` — 全マジック値の単一ソース (TTL/limits/thresholds/重み等)
- `backend/src/main.py` — FastAPIエントリ
- `backend/src/api/`
  - `chat.py` — エンドポイント + ストリーム制御 + retry ループ
  - `chat_events.py` — SSE イベント名・builder の単一ソース
  - `chat_pipeline.py` — Phase 2-4.5 の helper (style/preservation/critic/pairwise)
  - `chat_request.py` — multipart/JSON パーサ + ParsedChatRequest
  - `artifacts.py` `prompts.py` `health.py`
- `backend/src/agents/`
  - `root_agent.py` — root_coordinator (transfer to pptx/search)
  - `pptx_agent.py` — generate/edit skill scripts ラッパ
  - `search_agent.py` — GoogleSearchTool 単独 (builtin衝突回避のため隔離)
  - `mode/` — Phase 1 mode_spec schema + 決定論 inferrer
  - `style_schema.py` — Phase 2 Layer A+B (palette/typography/templates)
  - `preservation_schema.py` — Phase 3 EntitySet + PreservationScore
  - `critic_schema.py` — Phase 4 CriticResult + Phase 4.5 PairwiseResult
  - `tools/file_bridge.py` — 添付ファイル受け渡し
- `backend/src/services/`
  - `genai_client.py` — google-genai 共有 client + retry-with-backoff
  - `style_extractor.py` `style_cache.py` — Phase 2
  - `entity_extractor.py` `preservation.py` — Phase 3
  - `critic.py` — Phase 4 + 4.5 (run_critic / compare_pairwise / decide_winner)
  - `artifact_store.py` — 1h TTL in-memory
  - `pptx_skill.py` — pptx_inspect.js subprocess wrapper

### Frontend
- `frontend/src/config.ts` — API base URL + UI 定数 + downloadFromApi/Blob 共通ヘルパ
- `frontend/src/types/modeSpec.ts` — ModeSpec 型 + clientside 推定 (backend と同期)
- `frontend/src/components/`
  - `ChatLayout.tsx` `ChatView.tsx` `ChatMessageList.tsx`
  - `ModeSelector.tsx` — 折り畳み可能、localStorage 永続化
  - `PipelineProgress.tsx` — 入力欄上の進捗チップ列
  - `PptxPanel.tsx` `PptxSlideViewer.tsx` `PptxEditToolbar.tsx`
  - `PptxHistoryDropdown.tsx` — チャット内の OPFS 世代一覧
- `frontend/src/hooks/useChat.ts` — SSE ストリーム処理 + sessionId-aware abort
- `frontend/src/services/`
  - `chatHistory.ts` — localStorage チャット履歴
  - `pptxStorage.ts` — OPFS PPTX 永続化 (per-session, 30世代まで)

### Skills (PPTX 操作)
- `backend/skills/pptx/SKILL.md` + `references/`
- `scripts/generate_pptx.py` — PptxGenJS 新規作成
- `scripts/edit_pptx.py` — python-pptx 編集。30+ ops (text / fill / transform / shape CRUD / table / slide CRUD / **`copy_slide_from_artifact`**)
- `scripts/pptx_inspect.js` — Node 経由で SVG + PNG + shape 構造抽出

## SSE プロトコル

すべて `data: {...}\n\n` の単一形式。型は backend `chat_events.py` と frontend `useChat.ts` の `StreamEvent.type` で同期:

```
mode_spec / style_extracted / preservation / critic_result
pipeline_step / pairwise_compare / rollback
tool_call / tool_result / pptx_artifact / text(_chunk) / done / error
```

## Environment Setup

1. `gcloud auth application-default login` で Google Cloud 認証
2. `cp .env.example .env` で環境変数設定
3. 必須環境変数:
   - `GOOGLE_CLOUD_PROJECT` — Vertex AI 利用時
   - もしくは `GOOGLE_API_KEY` — Gemini API 直接利用時
4. オプション (チューニング): `MODEL_TIER_*`, `AGENT_*_MODEL`, `FEATURE_*` (config.py 参照)

詳細は [docs/architecture.md](docs/architecture.md) を参照。
