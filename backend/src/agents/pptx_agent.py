"""PPTX Agent - Presentation creation and editing.

All PPTX operations (create + edit) live in the pptx skill as scripts:
  - scripts/generate_pptx.py  — create new deck via PptxGenJS
  - scripts/edit_pptx.py      — edit existing deck via python-pptx

This agent is a thin wrapper that exposes those scripts through ADK's
SkillToolset. No Node/subprocess code lives in the Python layer.
"""

import contextvars
import logging
import pathlib

from google.adk.agents import LlmAgent
from google.adk.code_executors.unsafe_local_code_executor import UnsafeLocalCodeExecutor
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

from src.config import settings
from src.constants import DEFAULT_THREAD_ID, SKILL_SCRIPT_TIMEOUT

logger = logging.getLogger(__name__)

_SKILLS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "skills"

# Per-request state — contextvars are async-safe and auto-isolate per task.
# Currently unused by the agent itself, but kept as the integration point for
# the skill's HTTP bridge (edit_pptx.py / generate_pptx.py POST to /artifacts,
# and the backend links those to the active thread via source_artifact_id).
_thread_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pptx_thread_id", default=DEFAULT_THREAD_ID,
)


def set_pptx_thread_id(thread_id: str) -> None:
    _thread_id_var.set(thread_id)


def clear_pptx_thread_id() -> None:
    _thread_id_var.set(DEFAULT_THREAD_ID)


def build_pptx_agent() -> LlmAgent:
    """Build the PPTX agent wrapping the pptx skill's scripts."""
    pptx_skill_dir = _SKILLS_DIR / "pptx"

    tools: list = []
    if pptx_skill_dir.exists():
        try:
            pptx_skill = load_skill_from_dir(pptx_skill_dir)
            logger.info(f"Loaded PPTX skill: {pptx_skill.name}")
            tools.append(SkillToolset(
                skills=[pptx_skill],
                code_executor=UnsafeLocalCodeExecutor(),
                script_timeout=SKILL_SCRIPT_TIMEOUT,
            ))
        except Exception as e:
            logger.error(f"Failed to load PPTX skill: {e}")
    else:
        logger.warning(f"PPTX skill directory not found: {pptx_skill_dir}")

    return LlmAgent(
        name="pptx_agent",
        model=settings.pptx_agent_model,
        description=(
            "プレゼンテーション（PPTX）の作成・編集を担当。"
            "スライドデッキの新規作成、既存PPTXの編集（テキスト・配色・レイアウト変更）。"
        ),
        instruction=_PPTX_AGENT_INSTRUCTION,
        tools=tools,
    )


_PPTX_AGENT_INSTRUCTION = """\
あなたはプレゼンテーション（PPTX）の作成・編集を担当するエージェントです。

実行手段は「pptx」スキルの2本のスクリプトだけです。両方とも run_skill_script 経由で呼び出します。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【最重要ルール】artifact_id があれば必ず edit_pptx.py を使う
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ユーザーのメッセージに「artifact_id」が含まれている場合:
→ 必ず scripts/edit_pptx.py（既存PPTXの編集）を使用
→ generate_pptx.py で新規作成してはいけない（ユーザーの既存スライドが失われます）

「編集」には次のすべてが含まれます:
  - 既存シェイプのテキスト/色/位置サイズ変更
  - 新しい情報を調べてスライドを追加（duplicate_slide + text ops）
  - スライドの複製・削除・並べ替え

artifact_id が無い場合のみ、新規作成（generate_pptx.py）を使用してください。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【既存PPTX編集】scripts/edit_pptx.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ユーザーメッセージには各スライドの PNG と全シェイプの構造情報（テキスト内容・
位置・色）が既に添付されています。これを見て ops を決めてください。詳細は
スキルの references/editing.md にあります。

run_skill_script(
  skill_name="pptx",
  script_path="scripts/edit_pptx.py",
  script_args={
    "artifact_id": "abc-123",
    "ops": '[{"type":"text","slide":0,"shape":2,"para":0,"run":0,"text":"新タイトル"}]',
    "output_filename": "updated.pptx",
  },
)

ops は JSON 文字列として渡し、先頭から順に適用されます。スライドを追加/削除
した後は新しいインデックスで指定してください。

サポートされる ops:
  - text: {"type":"text", "slide":0, "shape":2, "para":0, "run":0, "text":"..."}
  - fill: {"type":"fill", "slide":0, "shape":2, "r":68, "g":114, "b":196}
  - transform: {"type":"transform", "slide":0, "shape":2, "x":..., "y":..., "cx":..., "cy":..., "rot":...}
  - duplicate_slide: {"type":"duplicate_slide", "source":3, "insert_after":3}
  - delete_slide: {"type":"delete_slide", "slide":4}

座標・サイズは EMU（1インチ = 914400 EMU）、rot は 60000分の1度（90度 = 5400000）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【新規作成】scripts/generate_pptx.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

artifact_id が無い場合のみ使用。詳細は references/pptxgenjs.md を参照。

run_skill_script(
  skill_name="pptx",
  script_path="scripts/generate_pptx.py",
  script_args={
    "code": "<PptxGenJS の JavaScript コード全文>",
    "output_filename": "deck.pptx",
  },
)

code の要件:
  - 全体を async IIFE で包む:  (async () => { ... })();
  - 出力は await pres.writeFile({ fileName: process.env.PPTX_OUTPUT_PATH })
  - pptxgenjs, react, react-dom, react-icons, sharp はグローバルインストール済み

デザインのガイドラインとアイコン使用パターンは SKILL.md と references/pptxgenjs.md
に記載されています。必ず load_skill で読み込んでから実装してください。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【結果の確認】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

どちらのスクリプトも stdout 末尾に __PPTX_ARTIFACT__ マーカー行を出力し、
サーバー側が自動的にユーザーへファイルを提供します。ダウンロードリンクは
応答テキストに含めないでください。視覚的な最終確認は次のターンで最新の PNG
がユーザーメッセージに再添付されるのでそれを見てください。

結果の報告は日本語で、プレゼンテーションの概要を簡潔に伝えてください。
"""
