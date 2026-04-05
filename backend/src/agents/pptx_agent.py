"""PPTX Agent - Presentation creation and editing."""

import contextvars
import logging
import os
import pathlib
import subprocess
import tempfile
from typing import Awaitable, Callable, TypeVar

from google.adk.agents import LlmAgent
from google.adk.code_executors.unsafe_local_code_executor import UnsafeLocalCodeExecutor
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from src.config import settings
from src.constants import (
    DEFAULT_THREAD_ID,
    PPTXGENJS_SCRIPT_TIMEOUT,
    SKILL_SCRIPT_TIMEOUT,
)
from src.services.artifact_store import get_artifact, store_artifact
from src.services.pptx_edit_bridge import bridge

logger = logging.getLogger(__name__)

# SSE marker key for detecting PPTX artifacts in tool responses
PPTX_ARTIFACT_MARKER = "__pptx_artifact__"

# Resolve skill directory relative to this file
_SKILLS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "skills"

# NODE_PATH for resolving globally-installed npm packages inside Docker
_NODE_PATH = os.environ.get("NODE_PATH", "/usr/lib/node_modules")

# Per-request state — contextvars are async-safe and auto-isolate per task.
_thread_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pptx_thread_id", default=DEFAULT_THREAD_ID,
)
_edit_session_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pptx_edit_session", default="",
)


def set_pptx_thread_id(thread_id: str) -> None:
    _thread_id_var.set(thread_id)


def clear_pptx_thread_id() -> None:
    _thread_id_var.set(DEFAULT_THREAD_ID)


def set_edit_session(session_id: str) -> None:
    _edit_session_var.set(session_id)


def clear_edit_session() -> None:
    _edit_session_var.set("")


def _session_id() -> str:
    """Session ID for bridge calls: edit-session override, else thread_id."""
    return _edit_session_var.get() or _thread_id_var.get()


_T = TypeVar("_T")


async def _bridge_call(name: str, fn: Callable[[], Awaitable[_T]]) -> dict | _T:
    """Run a bridge coroutine, returning {'error': ...} on failure.

    Collapses the identical try/except used by every edit_shape_* tool.
    """
    try:
        return await fn()
    except Exception as e:
        logger.error(f"{name} failed: {e}")
        return {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────
# Tool: New PPTX creation (PptxGenJS)
# ──────────────────────────────────────────────────────────────────────


def run_pptxgenjs(
    javascript_code: str,
    output_filename: str = "presentation.pptx",
) -> dict:
    """Execute PptxGenJS JavaScript code to generate a PPTX file from scratch.

    Use this tool when creating a brand-new presentation.
    Do NOT use this for editing an existing PPTX — use load_pptx / edit_shape_* instead.

    Args:
        javascript_code: Complete Node.js script using PptxGenJS.
            Must use async IIFE: (async () => { ... })();
            Must call pres.writeFile({ fileName: process.env.PPTX_OUTPUT_PATH })
        output_filename: Filename for the generated PPTX (default: presentation.pptx).

    Returns:
        Dict with artifact_id and download_url on success, or error details.
    """
    if not output_filename.endswith(".pptx"):
        output_filename += ".pptx"

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = os.path.join(tmpdir, "generate.js")
        output_path = os.path.join(tmpdir, output_filename)

        with open(script_path, "w") as f:
            f.write(javascript_code)

        try:
            result = subprocess.run(
                ["node", script_path],
                capture_output=True,
                text=True,
                timeout=PPTXGENJS_SCRIPT_TIMEOUT,
                cwd=tmpdir,
                env={
                    **os.environ,
                    "PPTX_OUTPUT_PATH": output_path,
                    "NODE_PATH": _NODE_PATH,
                },
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                logger.error(f"PptxGenJS script failed: {error_msg}")
                return {
                    "error": f"Script execution failed (exit code {result.returncode})",
                    "stderr": error_msg[:2000],
                    "stdout": result.stdout[:1000] if result.stdout else "",
                }

            if not os.path.exists(output_path):
                return {
                    "error": "No .pptx file was generated. Make sure to call "
                    "pres.writeFile({ fileName: process.env.PPTX_OUTPUT_PATH })",
                    "stdout": result.stdout[:1000] if result.stdout else "",
                }

            with open(output_path, "rb") as f:
                data = f.read()

            artifact_id = store_artifact(
                thread_id=_thread_id_var.get(),
                filename=output_filename,
                data=data,
            )

            logger.info(
                f"PPTX generated: {output_filename} ({len(data)} bytes), "
                f"artifact_id={artifact_id}"
            )

            return {
                PPTX_ARTIFACT_MARKER: True,
                "artifact_id": artifact_id,
                "filename": output_filename,
                "size_bytes": len(data),
                "download_url": f"/artifacts/{artifact_id}",
                "stdout": result.stdout[:500] if result.stdout else "",
            }

        except subprocess.TimeoutExpired:
            return {"error": f"Script execution timed out ({PPTXGENJS_SCRIPT_TIMEOUT}s limit)"}
        except FileNotFoundError:
            return {
                "error": "Node.js is not installed. Please install Node.js to use PptxGenJS."
            }
        except Exception as e:
            logger.error(f"PptxGenJS execution error: {e}")
            return {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────
# Tools: Existing PPTX editing (pptx-svg bridge)
# ──────────────────────────────────────────────────────────────────────


async def load_pptx(artifact_id: str) -> dict:
    """Load an existing PPTX from the artifact store for editing.

    Call this first before using any edit_shape_* tools.
    The artifact_id is provided in the user's context when they have an edited PPTX.

    Args:
        artifact_id: The artifact ID of the PPTX to load.

    Returns:
        Dict with slide_count and per-slide shape summaries.
    """
    artifact = get_artifact(artifact_id)
    if not artifact:
        return {"error": f"Artifact not found: {artifact_id}"}

    async def _load() -> dict:
        session_id = _session_id()
        await bridge.load_pptx(session_id, artifact.data)
        info = await bridge.get_all_slides_info(session_id)
        return {
            "loaded_artifact_id": artifact_id,
            "filename": artifact.filename,
            **info,
        }

    return await _bridge_call("load_pptx", _load)


async def get_slide_shapes(slide_idx: int) -> dict:
    """Get detailed shape information for a specific slide.

    Returns shapes with their positions (EMU), fill colors, and text content.
    Use this to understand the current state of a slide before editing.

    Args:
        slide_idx: 0-based slide index.

    Returns:
        Dict with shapes list. Each shape has: idx, shape_type, x, y, cx, cy, fill_hex, text_runs.
    """
    async def _get() -> dict:
        info = await bridge.get_slide_info(_session_id(), slide_idx)
        # Remove SVG from response to save context (too large)
        info.pop("svg", None)
        return info

    return await _bridge_call("get_slide_shapes", _get)


async def edit_shape_text(
    slide_idx: int,
    shape_idx: int,
    para_idx: int,
    run_idx: int,
    new_text: str,
) -> dict:
    """Edit text in a specific shape's paragraph run.

    Args:
        slide_idx: 0-based slide index.
        shape_idx: Shape index (from get_slide_shapes / load_pptx results).
        para_idx: Paragraph index within the shape.
        run_idx: Run index within the paragraph.
        new_text: New text content for this run.

    Returns:
        Dict with ok=true on success.
    """
    return await _bridge_call(
        "edit_shape_text",
        lambda: bridge.update_shape_text(
            _session_id(), slide_idx, shape_idx, para_idx, run_idx, new_text,
        ),
    )


async def edit_shape_fill(
    slide_idx: int,
    shape_idx: int,
    r: int,
    g: int,
    b: int,
) -> dict:
    """Change a shape's fill color.

    Args:
        slide_idx: 0-based slide index.
        shape_idx: Shape index.
        r: Red (0-255).
        g: Green (0-255).
        b: Blue (0-255).

    Returns:
        Dict with ok=true on success.
    """
    return await _bridge_call(
        "edit_shape_fill",
        lambda: bridge.update_shape_fill(_session_id(), slide_idx, shape_idx, r, g, b),
    )


async def edit_shape_transform(
    slide_idx: int,
    shape_idx: int,
    x: int,
    y: int,
    cx: int,
    cy: int,
    rot: int = 0,
) -> dict:
    """Move/resize a shape. All values in EMU (1 inch = 914400 EMU).

    Args:
        slide_idx: 0-based slide index.
        shape_idx: Shape index.
        x: X position in EMU.
        y: Y position in EMU.
        cx: Width in EMU.
        cy: Height in EMU.
        rot: Rotation in 60000ths of a degree (default: 0).

    Returns:
        Dict with ok=true on success.
    """
    return await _bridge_call(
        "edit_shape_transform",
        lambda: bridge.update_shape_transform(
            _session_id(), slide_idx, shape_idx, x, y, cx, cy, rot,
        ),
    )


async def save_edited_pptx(output_filename: str = "presentation.pptx") -> dict:
    """Export the edited PPTX and save it as a new artifact.

    Call this after making all edits with edit_shape_* tools.

    Args:
        output_filename: Filename for the saved PPTX.

    Returns:
        Dict with artifact_id and download_url on success.
    """
    if not output_filename.endswith(".pptx"):
        output_filename += ".pptx"

    async def _save() -> dict:
        data = await bridge.export_pptx(_session_id())
        artifact_id = store_artifact(
            thread_id=_thread_id_var.get(),
            filename=output_filename,
            data=data,
        )
        logger.info(
            f"Edited PPTX saved: {output_filename} ({len(data)} bytes), "
            f"artifact_id={artifact_id}"
        )
        return {
            PPTX_ARTIFACT_MARKER: True,
            "artifact_id": artifact_id,
            "filename": output_filename,
            "size_bytes": len(data),
            "download_url": f"/artifacts/{artifact_id}",
        }

    return await _bridge_call("save_edited_pptx", _save)


async def render_slide_svg(slide_idx: int) -> dict:
    """Render a slide as SVG for visual QA.

    Use after editing to visually verify the result. Returns the SVG string
    and structured shape info.

    Args:
        slide_idx: 0-based slide index.

    Returns:
        Dict with svg (SVG string) and shapes info.
    """
    return await _bridge_call(
        "render_slide_svg",
        lambda: bridge.get_slide_info(_session_id(), slide_idx),
    )


# ──────────────────────────────────────────────────────────────────────
# Agent builder
# ──────────────────────────────────────────────────────────────────────


def build_pptx_agent() -> LlmAgent:
    """Build the PPTX agent with creation and editing tools."""
    pptx_skill_dir = _SKILLS_DIR / "pptx"

    tools: list = [
        # Creation
        FunctionTool(run_pptxgenjs),
        # Editing (pptx-svg bridge)
        FunctionTool(load_pptx),
        FunctionTool(get_slide_shapes),
        FunctionTool(edit_shape_text),
        FunctionTool(edit_shape_fill),
        FunctionTool(edit_shape_transform),
        FunctionTool(save_edited_pptx),
        FunctionTool(render_slide_svg),
    ]

    if pptx_skill_dir.exists():
        try:
            pptx_skill = load_skill_from_dir(pptx_skill_dir)
            logger.info(f"Loaded PPTX skill: {pptx_skill.name}")

            skill_toolset = SkillToolset(
                skills=[pptx_skill],
                code_executor=UnsafeLocalCodeExecutor(),
                script_timeout=SKILL_SCRIPT_TIMEOUT,
            )
            tools.append(skill_toolset)
        except Exception as e:
            logger.error(f"Failed to load PPTX skill: {e}")
    else:
        logger.warning(f"PPTX skill directory not found: {pptx_skill_dir}")

    return LlmAgent(
        name="pptx_agent",
        model=settings.genai_model,
        description=(
            "プレゼンテーション（PPTX）の作成・編集を担当。"
            "スライドデッキの新規作成、既存PPTXの編集（テキスト・配色・レイアウト変更）。"
        ),
        instruction=_PPTX_AGENT_INSTRUCTION,
        tools=tools,
    )


_PPTX_AGENT_INSTRUCTION = """\
あなたはプレゼンテーション（PPTX）の作成・編集を担当するエージェントです。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【最重要ルール】artifact_id があれば必ず編集モードを使え
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ユーザーのメッセージに「artifact_id」が含まれている場合:
→ **必ず load_pptx → edit_shape_* → save_edited_pptx の編集フローを使用**
→ **絶対に run_pptxgenjs で新規作成してはいけない**
→ ユーザーの既存スライドの内容・デザインを保持したまま変更を加える

artifact_id が含まれていない場合のみ、新規作成（run_pptxgenjs）を使用。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【既存PPTX編集フロー（pptx-svg ブリッジ）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1: ロード
  load_pptx(artifact_id="...")
  → 全スライドのシェイプ情報が返る

Step 2: 確認（必要に応じて）
  get_slide_shapes(slide_idx=N)
  → 特定スライドの詳細

Step 3: 編集
  edit_shape_text(slide_idx, shape_idx, para_idx, run_idx, new_text)
  edit_shape_fill(slide_idx, shape_idx, r, g, b)
  edit_shape_transform(slide_idx, shape_idx, x, y, cx, cy, rot)

Step 4: QA（推奨）
  render_slide_svg(slide_idx=N)
  → SVGで視覚的に確認

Step 5: 保存
  save_edited_pptx("filename.pptx")

シェイプ情報の読み方:
- idx: シェイプインデックス（edit_shape_* の shape_idx に指定）
- shape_type: "sp"(図形), "pic"(画像), "graphicFrame"(表/グラフ)
- x, y: 位置（EMU。1インチ = 914400）
- cx, cy: サイズ（EMU）
- fill_hex: 塗りつぶし色（6桁hex）
- text_runs: [{pi: 段落idx, ri: ランidx, text: "内容"}]

編集例:
  load_pptx("abc-123")
  edit_shape_text(0, 2, 0, 0, "新タイトル")  # スライド0のシェイプ2のテキスト変更
  edit_shape_fill(0, 2, 68, 114, 196)          # 青色に変更
  save_edited_pptx("updated.pptx")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【新規作成（PptxGenJS）— artifact_id がない場合のみ】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. load_skill で "pptx" スキルを読み込む（デザインガイドライン取得）
2. run_pptxgenjs で PptxGenJS コードを実行

重要:
- 必ず async IIFE `(async () => { ... })();` で全体を包むこと
- 必ず `process.env.PPTX_OUTPUT_PATH` を出力先パスとして使用すること
- `await pres.writeFile({ fileName: outputPath })` で出力すること
- pptxgenjs, react, react-dom, react-icons, sharp はグローバルインストール済み

【アイコンの使い方 — 必須】

すべてのスライドにアイコンを積極的に使用してください。react-icons + sharp が\
グローバルインストール済みです。以下のヘルパー関数をスクリプト冒頭に定義してください:

```javascript
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

function renderIconSvg(IconComponent, color, size) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color: color, size: String(size) })
  );
}

async function iconToBase64Png(IconComponent, color, size) {
  const svg = renderIconSvg(IconComponent, color || "#000000", size || 256);
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + pngBuffer.toString("base64");
}
```

使用例:
```javascript
const { FaCheckCircle, FaChartLine, FaUsers } = require("react-icons/fa");
const iconData = await iconToBase64Png(FaCheckCircle, "4472C4", 256);
slide.addImage({ data: iconData, x: 1, y: 1, w: 0.5, h: 0.5 });
```

主要なアイコンライブラリ:
- `react-icons/fa` — Font Awesome
- `react-icons/md` — Material Design
- `react-icons/hi` — Heroicons
- `react-icons/bi` — Bootstrap Icons

【デザインのポイント】
- スキルの指示に含まれるデザインガイドラインに従ってください
- 単調なレイアウトの繰り返しを避け、スライドごとに異なるレイアウトを使用
- タイトルスライドはダーク背景、コンテンツスライドはライト背景が効果的
- テキストだけのスライドは避け、必ずアイコンやシェイプなどのビジュアル要素を追加

【結果の報告】
- PPTXファイルの生成・保存が成功したら、プレゼンテーションの概要を日本語で報告
- ダウンロードリンクやURLは絶対にテキストに含めないでください
- ファイルは run_pptxgenjs / save_edited_pptx の結果として自動的にユーザーに提供されます
"""
