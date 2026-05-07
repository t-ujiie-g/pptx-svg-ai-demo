# Improvements Log

実装済み改善の履歴。設計判断の根拠を残すための作業ログで、現在の動作仕様は
[architecture.md](architecture.md) を参照すること (こちらは時系列のスナップショット)。

## Phase 1〜4.5 (パイプライン本体)

| Phase | 内容 |
|---|---|
| 1 | mode_spec 3スロットモデル (intent / style_source / inputs) |
| 2 | スタイル抽出 (Layer A: palette/typography, Layer B: cover/agenda 等のテンプレート) |
| 3 | 情報保全チェック (pre-gen エンティティ抽出 + post-gen 比較 → ratio) |
| 4 | Critic 5軸評価 (intent_fit / design / consistency / info_density / preservation) |
| 4.5 | リトライ + Critic v2 + ペアワイズ + ロールバック |

## 改善ステップ (運用中に発見した課題への対応)

| Step | テーマ | 主要な変更 |
|---|---|---|
| A1 | ModeSelector がリクエスト中にリセット | useEffect を `disabled` でガード、styleRefFile の永続化を SSE 経由に |
| A2 | SSE 進捗が遅延して見える | `PipelineProgress` チップ列を入力欄上に配置 |
| B  | 他チャットのスライド汚染 | useChat に sessionId-aware abort、`onPptxArtifactChange` の race 防御、handleUpdateSession 修正 |
| C  | チャット単位 OPFS + 版管理 | `services/pptxStorage.ts` (OPFS) + `PptxHistoryDropdown` + Viewer の OPFS フォールバック |
| D  | テンプレ忠実再現 | `edit_pptx.py:op_copy_slide_from_artifact` で別 PPTX のスライドを deep-copy |
| E  | 豆腐文字 (PNG レンダ) | Dockerfile に `fonts-noto-cjk` 追加 |
| F  | ペアワイズ精度 | プロンプト強化 (スライド番号同士で対比) + `decide_winner` を v2-bias に |
| G  | 429 RESOURCE_EXHAUSTED | `with_genai_retry` 共通ヘルパ + feature flag による段階OFF |
| H  | Gemini 3 builtin tool 衝突 | `search_agent` を新設し GoogleSearchTool を隔離 |

## リファクタ (2026-05-07)

- `chat.py` (1137行) を 4 モジュールに分割
  - `chat.py` (389) — endpoint + streaming + retry loop
  - `chat_events.py` (103) — SSE 名・builder の単一ソース
  - `chat_pipeline.py` (368) — Phase 2-4.5 helpers
  - `chat_request.py` (459) — multipart/JSON parser + ParsedChatRequest
- 共通 `downloadFromBlob` を `config.ts` に抽出 (PptxHistoryDropdown と PptxSlideViewer の重複解消)
- `STATUS_COMPLETED` / `STATUS_FAILED` / pipeline step 名を chat_events.py に集約
- CLAUDE.md / docs/architecture.md を最新仕様に書き直し
