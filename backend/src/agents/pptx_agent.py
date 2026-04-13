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
            "スライドデッキの新規作成、既存PPTXの編集（テキスト・配色・レイアウト・"
            "図形追加/削除・枠線・テキスト書式・スライド管理）。"
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
  - 新しいシェイプの追加（図形・テキストボックス・画像）
  - シェイプの削除・複製
  - テキストの書式変更（太字・斜体・フォント・サイズ・色）
  - 段落やランの追加
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

■ シェイプの内容変更:
  text:            {"type":"text", "slide":0, "shape":2, "para":0, "run":0, "text":"..."}
  fill:            {"type":"fill", "slide":0, "shape":2, "r":68, "g":114, "b":196}
  fill_none:       {"type":"fill_none", "slide":0, "shape":2}
  transform:       {"type":"transform", "slide":0, "shape":2, "x":X, "y":Y, "cx":CX, "cy":CY, "rot":ROT}
  stroke:          {"type":"stroke", "slide":0, "shape":2, "r":0, "g":0, "b":0, "width":12700, "dash":"solid"}
  stroke_none:     {"type":"stroke_none", "slide":0, "shape":2}

■ シェイプの追加・削除・複製:
  add_shape:       {"type":"add_shape", "slide":0, "shape_type":"rect", "x":X, "y":Y, "cx":CX, "cy":CY,
                    "fill_r":R, "fill_g":G, "fill_b":B,
                    "text":"テキスト", "font_size":14, "font_name":"Yu Gothic", "font_bold":true,
                    "color_r":255, "color_g":255, "color_b":255, "align":"center",
                    "stroke_r":0, "stroke_g":0, "stroke_b":0, "stroke_width":12700}
                   ※ fill/text/stroke/font は全て省略可。1つの op でテキスト付き図形を作成可能。
                   shape_type: rect, ellipse, roundRect, triangle, diamond, rightArrow, leftArrow 等
  delete_shape:    {"type":"delete_shape", "slide":0, "shape":2}
  duplicate_shape: {"type":"duplicate_shape", "slide":0, "shape":2, "dx":457200, "dy":457200}

■ テキスト編集:
  add_paragraph:   {"type":"add_paragraph", "slide":0, "shape":2, "text":"...", "align":"center"}
  add_run:         {"type":"add_run", "slide":0, "shape":2, "para":0, "text":"..."}
  text_style:      {"type":"text_style", "slide":0, "shape":2, "para":0, "run":0,
                    "bold":true, "italic":false, "font_size":18, "font_name":"Yu Gothic",
                    "color_r":255, "color_g":0, "color_b":0}
                   ※ 全フィールド省略可。指定したもののみ変更。
  paragraph_align: {"type":"paragraph_align", "slide":0, "shape":2, "para":0, "align":"center"}
                   align: left, center, right, justify

■ 画像の追加:
  add_image:       {"type":"add_image", "slide":0, "image_base64":"...", "mime":"image/png",
                    "x":X, "y":Y, "cx":CX, "cy":CY}

■ スライド管理:
  duplicate_slide: {"type":"duplicate_slide", "source":3, "insert_after":3}
  delete_slide:    {"type":"delete_slide", "slide":4}
  reorder_slides:  {"type":"reorder_slides", "order":[2,0,1,3]}

座標・サイズは EMU（1インチ = 914400 EMU）、rot は 60000分の1度（90度 = 5400000）。
stroke の width も EMU（1pt = 12700 EMU）。font_size は pt 単位（例: 18）。
dash: solid, dash, dot, dashDot, lgDash

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
