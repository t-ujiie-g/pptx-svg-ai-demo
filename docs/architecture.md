# Architecture

PPTX 生成エージェントの全体像、評価パイプライン、SSE プロトコル、運用上の調整ポイントをまとめたリファレンス。新メンバー向けの導入と、保守時の "どこを直せば何に効くか" のマップを兼ねる。

## 1. 全体像

```
┌─────────────────────────── Frontend ───────────────────────────┐
│ React + TS, Vite                                                │
│  ChatLayout                                                     │
│   ├─ Sidebar (sessions, OPFS削除連動)                            │
│   ├─ ChatView                                                   │
│   │   ├─ ModeSelector (折り畳み, localStorage)                   │
│   │   ├─ PipelineProgress (style/preservation/critic/...)        │
│   │   ├─ ChatMessageList (typing indicator + tool history)       │
│   │   └─ 入力 + 添付 + style_ref                                 │
│   └─ PptxPanel                                                  │
│       ├─ PptxHistoryDropdown (OPFS世代)                          │
│       └─ PptxSlideViewer (編集 + OPFSフォールバック)              │
│  永続化: localStorage(履歴) + OPFS(PPTX bytes / per session)     │
└─────────────────────────────┬───────────────────────────────────┘
                              │ multipart / SSE
┌─────────────────────────────▼─────────────────────────────────┐
│ Backend (FastAPI + Google ADK)                                 │
│  /chat/stream                                                  │
│   ├─ chat_request.parse_request                                │
│   ├─ chat_pipeline.maybe_extract_style       (Phase 2)          │
│   ├─ chat_pipeline.maybe_extract_target_entities (Phase 3 pre)  │
│   ├─ ADK Runner: agent v1                                      │
│   ├─ chat_pipeline.run_preservation_check    (Phase 3 post)     │
│   ├─ chat_pipeline.run_critic_review          (Phase 4)         │
│   └─ retry loop (verdict=retry なら)                            │
│       ├─ Runner: agent v2                                      │
│       ├─ 再 preservation + critic                               │
│       ├─ run_pairwise_compare (Phase 4.5)                       │
│       └─ rollback (v1 winner なら)                              │
│                                                                │
│  Agents (ADK LlmAgent)                                         │
│   ├─ root_coordinator → 委譲 (pptx_agent / search_agent)        │
│   ├─ pptx_agent       → skill scripts                           │
│   └─ search_agent     → GoogleSearchTool 単独 (builtin隔離)     │
│                                                                │
│  Skills (backend/skills/pptx/scripts/)                         │
│   ├─ generate_pptx.py (Node.js + PptxGenJS)                     │
│   ├─ edit_pptx.py (python-pptx; 30+ ops)                        │
│   └─ pptx_inspect.js (SVG → PNG + 構造)                         │
│                                                                │
│  Persistence: artifact_store (1h TTL in-memory)                │
└────────────────────────────────────────────────────────────────┘
```

## 2. リクエストフロー (SSE 順)

```
1. mode_spec       … parse_request 完了直後
2. style_extracted … Phase 2 (Layer A+B 抽出) — feature_style_extraction
3. pptx_artifact   … (アップロードがあれば即座に preview 用)
4. tool_call/tool_result/pptx_artifact/text_chunk  … agent v1 実行中
5. preservation    … Phase 3 (polish/restructure 時のみ) — feature_preservation_check
6. critic_result   … Phase 4 — feature_critic_review
   verdict=retry かつ feature_critic_retry=True のとき:
7. pipeline_step (retry_start)
8. tool_*/pptx_artifact/text_chunk  … agent v2 実行中
9. preservation (v2)
10. critic_result (v2)
11. pairwise_compare
12. rollback + pptx_artifact (v1 が勝者の時のみ)
13. done
```

すべて `data: {...}\n\n` 形式。イベント名は `backend/src/api/chat_events.py` と `frontend/src/hooks/useChat.ts:StreamEvent.type` で同期。

## 3. ModeSpec — 3スロットモデル

ユーザーの「何をしたいか」を 3 軸で表現する。Phase 1 で導入。

### Slot 1: Input (artifact 引数)
- `target_artifact_id`: 編集対象 (任意。`tweak`/`polish` には必須)
- `style_ref_artifact_id`: スタイル参照 (任意。`from-ref`/`mix` には必須)

### Slot 2: Intent
| 値 | 意味 | バリデータ閾値 (preservation) |
|---|---|---|
| `tweak` | 微修正、構造保持 | チェックなし |
| `polish` | 内容を活かしてレイアウト整形 | 0.90 |
| `restructure` | レイアウト・構成をガラッと変える | 0.70 |
| `from-scratch` | ゼロから新規作成 | チェックなし |

### Slot 3: Style Source
| `kind` | 抽出元 |
|---|---|
| `from-target` | target からスタイル抽出 |
| `from-ref` | style_ref からスタイル抽出 |
| `preset` | best-practice / bold / dense / minimal |
| `mix` | style_ref + preset の組合せ |

**自動推定**: `agents/mode/inferrer.py` (バックエンド) と `frontend/src/types/modeSpec.ts` (フロント) で同一ルール。フロントで先行表示し、バックエンドが最終確定。

## 4. 評価パイプライン詳細

### Phase 2: スタイル抽出 (Layer A + Layer B)
- **Layer A** (palette / typography / geometry / decoration / tone_tags) を Gemini lite tier で抽出
- **Layer B** (slide templates: cover / closing / agenda / content_*) を **同一呼出** で抽出
- artifact_id でキャッシュ (TTL: ARTIFACT_TTL = 1h)
- `services/style_extractor.py` + `services/style_cache.py`

### Phase 3: 情報保全
- **pre-gen**: target からエンティティ (person/number/date/money/...) を Gemini lite tier で抽出
- ユーザーメッセージに「保全すべき情報」ブロックを注入し、agent に明示
- **post-gen**: 出力 PPTX からも同様に抽出 → ratio = matched/total を計算 (NFKC + casefold + 数値ノイズ除去)
- intent 別閾値 (polish=0.90 / restructure=0.70) を割ったら critic に欠損リストを渡す
- `services/entity_extractor.py` + `services/preservation.py`

### Phase 4: Critic レビュー
- 5軸評価: `intent_fit / design / consistency / info_density / preservation`
- intent 別重みで weighted score を **service 側で** 計算 (LLM は score だけ出す)
- verdict 補正:
  - LLM `reject` → そのまま `reject`
  - weighted ≥ 0.70 かつ issues 無し → `accept`
  - weighted < 0.40 → `reject`
  - それ以外 → `retry`
- `services/critic.py:run_critic`

### Phase 4.5: リトライ + ペアワイズ + ロールバック
- `verdict=retry` なら、Critic の retry_hint と preservation 欠損を注入した「継続メッセージ」を ADK の同 session に投げて v2 生成
- v2 にも preservation + critic を回し、最後に **ペアワイズ比較** (compare_pairwise) で v1 vs v2 の勝者を判定
- `decide_winner` は LLM 判定 + weighted の tie-break margin (0.03) を組合せ。**tie 時は v2 寄り** (修正意図を尊重)
- v1 が勝った場合のみ `rollback` イベント + v1 の `pptx_artifact` 再送 (UI が最新を表示する慣例に合わせる)
- リトライ回数上限: `CRITIC_MAX_RETRIES = 1` (定数で調整可)

## 5. Skill Scripts (PPTX 操作)

| Script | 用途 | エンジン |
|---|---|---|
| `generate_pptx.py` | 新規作成 | Node.js + PptxGenJS |
| `edit_pptx.py` | 編集 (30+ ops: text/fill/transform/shape/table/slide CRUD) | python-pptx |
| `pptx_inspect.js` | SVG レンダ + 構造抽出 (PNGはCritic用) | Node.js + jsdom + sharp |

### `copy_slide_from_artifact` op (Step D)
別 PPTX artifact から slide を deep-copy する `edit_pptx.py` の op。テンプレ (cover/agenda) を **そのまま** 流用するときに使用:

```
1. generate_pptx.py で本文だけ生成 → artifact A
2. edit_pptx.py(artifact_id=A, ops=[
     {"type":"copy_slide_from_artifact", "source_artifact_id": style_ref_id, "src_slide": 0, "insert_at": 0},
     {"type":"text", "slide": 0, ...}  # <<TITLE>> を実テキストに置換
   ])
```

埋め込み画像 (Picture shape) は cross-package なので `skipped_pictures` でカウントして agent に通知 → 必要なら `add_image` op で補完。

## 6. 永続化レイヤ

| レイヤ | 場所 | TTL | 用途 |
|---|---|---|---|
| backend artifact_store | RAM | 1 hour | 生成直後の preview / 編集 PUT / SSE 転送 |
| frontend OPFS | ブラウザ | (~30世代/session) | リロード後の表示・DL、版履歴 |
| localStorage | ブラウザ | 永続 | チャット履歴 (Message + 参照 artifact_id) |

OPFS フォールバック: Backend が 404 (TTL 切れ等) のとき PptxSlideViewer は OPFS から自動復元する。

## 7. Feature Flags (config.py)

quota / コスト制約に応じて段階を OFF にできる:

| Flag | デフォルト | 影響 |
|---|---|---|
| `feature_style_extraction` | True | Phase 2 (-1 LLM call) |
| `feature_preservation_check` | True | Phase 3 (-2 LLM calls; pre + post) |
| `feature_critic_review` | True | Phase 4 (-1 LLM call); リトライも自動停止 |
| `feature_critic_retry` | True | Phase 4.5 (-1〜4 LLM calls) |

最大 burst: 1 リクエストあたり ~10 LLM 呼出 (style + 2x entity + agent v1 + critic + agent v2 + 2x entity + critic + pairwise)。

## 8. Quota & 信頼性

- `services/genai_client.py:with_genai_retry` が 429/500/503/504 に対し指数 backoff + jitter で最大 5 回リトライ
- ADK Runner の Gemini 呼出は ADK 内部のリトライ機構が動く
- 直接 SDK を呼ぶ全サービス (style_extractor / entity_extractor / critic) はこのラッパで統一

## 9. モデル割当

`config.py` の tier 抽象化:
```
MODEL_TIER_HIGH = "gemini-3.1-pro-preview"      # 推論重 / Critic v2 / pptx_agent
MODEL_TIER_MID  = "gemini-3-flash-preview"       # root / search / critic
MODEL_TIER_LITE = "gemini-3.1-flash-lite-preview"  # style / entity 抽出
```

各 agent / service は `agent_*_model = "tier:high|mid|lite"` で参照し、`resolve_model()` 経由で具体IDに解決される。`.env` で個別上書き可能。

## 10. 開発者向けマップ

「○○を変えたい」→ 「ここを見ろ」のショートカット:

| やりたいこと | ファイル |
|---|---|
| SSE イベントを追加 | `api/chat_events.py` (定数) + `chat.py` or `chat_pipeline.py` (送出) + `frontend/hooks/useChat.ts` (受信) |
| 新しい Critic 評価軸 | `agents/critic_schema.py` (CriticScores) + `constants.py` (CRITIC_WEIGHTS_BY_INTENT) + `services/critic.py:_PROMPT` |
| 新しい preservation entity 種類 | `agents/preservation_schema.py` (EntityType) + `services/entity_extractor.py:_EXTRACTION_PROMPT` |
| 新しい mode preset | `frontend/src/types/modeSpec.ts` (StylePreset) + `agents/mode/schema.py` (StylePreset) |
| 新しい style template kind | `agents/style_schema.py` (TemplateKind) + `services/style_extractor.py:_EXTRACTION_PROMPT` |
| 新しい edit op | `skills/pptx/scripts/edit_pptx.py` (op_*関数 + OP_HANDLERS) |
| OPFS スキーマ変更 | `frontend/src/services/pptxStorage.ts` |

## 11. ディレクトリ構造 (ざっくり)

```
backend/src/
  api/        chat.py + chat_events/pipeline/request + artifacts + prompts + health
  agents/     root + pptx + search + mode/ + *_schema.py
  services/   genai_client, style_*, entity_*, preservation, critic, artifact_store, pptx_skill
  config.py   constants.py  main.py
backend/skills/pptx/
  SKILL.md  references/  scripts/  (generate/edit/inspect/artifact_client)
frontend/src/
  components/ ChatLayout, ChatView, ChatMessageList, ModeSelector, PipelineProgress,
              PptxPanel, PptxSlideViewer, PptxHistoryDropdown, ...
  hooks/      useChat (SSE), usePptxRenderer, useFileAttachment, useTheme, ...
  services/   chatHistory, pptxStorage, savedPrompts, templateUtils
  types/      modeSpec
docs/
  architecture.md (これ)
  improvements.md (履歴)
```

## 12. テストを増やすとしたら

現状は smoke test ベース。優先度高いのは:

- `services/preservation.py` のスコア計算 (intent別閾値, normalize, missing 検出)
- `services/critic.py:decide_winner` の境界条件 (LLM/weighted 一致、tie-break)
- `agents/mode/inferrer.py` の規則テーブル (バックエンド/フロント同期維持)
- `skills/pptx/scripts/edit_pptx.py:op_copy_slide_from_artifact` の picture skip カウント

詳細実装履歴は [improvements.md](improvements.md) を参照。
