"""PPTX Agent - Presentation creation using Anthropic's PPTX skill with ADK SkillToolset."""

import logging
import os
import pathlib
import subprocess
import tempfile

from google.adk.agents import LlmAgent
from google.adk.code_executors.unsafe_local_code_executor import UnsafeLocalCodeExecutor
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from src.config import settings
from src.services.artifact_store import store_artifact

logger = logging.getLogger(__name__)

# SSE marker key for detecting PPTX artifacts in tool responses
PPTX_ARTIFACT_MARKER = "__pptx_artifact__"

# Resolve skill directory relative to this file
_SKILLS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "skills"

# NODE_PATH for resolving globally-installed npm packages inside Docker
_NODE_PATH = os.environ.get("NODE_PATH", "/usr/lib/node_modules")

# Per-request thread_id for artifact storage (simple global, single-threaded async)
_current_thread_id: str = "default"


def set_pptx_thread_id(thread_id: str) -> None:
    """Set the current thread_id for artifact storage."""
    global _current_thread_id  # noqa: PLW0603
    _current_thread_id = thread_id


def clear_pptx_thread_id() -> None:
    """Clear the current thread_id."""
    global _current_thread_id  # noqa: PLW0603
    _current_thread_id = "default"


def run_pptxgenjs(
    javascript_code: str,
    output_filename: str = "presentation.pptx",
) -> dict:
    """Execute PptxGenJS JavaScript code to generate a PPTX file.

    This tool runs a Node.js script that uses the PptxGenJS library to create
    a PowerPoint presentation. The generated file is automatically saved as
    a downloadable artifact.

    Args:
        javascript_code: Complete Node.js script using PptxGenJS.
            The script MUST call pres.writeFile() with the output path.
            Use `const outputPath = process.env.PPTX_OUTPUT_PATH;` to get
            the output file path, then call `pres.writeFile({ fileName: outputPath })`.

            Example:
            ```
            const pptxgen = require("pptxgenjs");
            const pres = new pptxgen();
            const outputPath = process.env.PPTX_OUTPUT_PATH;

            let slide = pres.addSlide();
            slide.addText("Hello World", { x: 1, y: 1, fontSize: 24 });

            pres.writeFile({ fileName: outputPath }).then(() => {
              console.log("Done");
            });
            ```
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
                timeout=120,
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
                pptx_files = [f for f in os.listdir(tmpdir) if f.endswith(".pptx")]
                if pptx_files:
                    output_path = os.path.join(tmpdir, pptx_files[0])
                    output_filename = pptx_files[0]
                else:
                    return {
                        "error": "No .pptx file was generated. Make sure to call "
                        "pres.writeFile({ fileName: process.env.PPTX_OUTPUT_PATH })",
                        "stdout": result.stdout[:1000] if result.stdout else "",
                    }

            with open(output_path, "rb") as f:
                data = f.read()

            artifact_id = store_artifact(
                thread_id=_current_thread_id,
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
            return {"error": "Script execution timed out (120s limit)"}
        except FileNotFoundError:
            return {
                "error": "Node.js is not installed. Please install Node.js to use PptxGenJS."
            }
        except Exception as e:
            logger.error(f"PptxGenJS execution error: {e}")
            return {"error": str(e)}


def build_pptx_agent() -> LlmAgent:
    """Build the PPTX agent with SkillToolset."""
    pptx_skill_dir = _SKILLS_DIR / "pptx"

    tools: list = [FunctionTool(run_pptxgenjs)]

    if pptx_skill_dir.exists():
        try:
            pptx_skill = load_skill_from_dir(pptx_skill_dir)
            logger.info(f"Loaded PPTX skill: {pptx_skill.name}")

            skill_toolset = SkillToolset(
                skills=[pptx_skill],
                code_executor=UnsafeLocalCodeExecutor(),
                script_timeout=600,
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
            "スライドデッキの新規作成、テンプレートからの編集、既存PPTXの分析。"
        ),
        instruction=_PPTX_AGENT_INSTRUCTION,
        tools=tools,
    )


_PPTX_AGENT_INSTRUCTION = """\
あなたはプレゼンテーション（PPTX）の作成・編集を担当するエージェントです。

【プレゼンテーション新規作成の手順】

1. まず load_skill を使って "pptx" スキルの指示を読み込んでください。
   デザインガイドライン（配色、フォント、レイアウト）が含まれています。

2. 必要に応じて load_skill_resource で references/pptxgenjs.md を読み込み、
   PptxGenJS の API リファレンスを確認してください。

3. run_pptxgenjs ツールを使って PptxGenJS のJavaScriptコードを実行し、
   PPTXファイルを生成してください。

重要:
- 必ず async IIFE `(async () => { ... })();` で全体を包むこと（await を使うため）
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
- `react-icons/fa` — Font Awesome (FaCheck, FaUsers, FaChartLine, FaCog, FaLightbulb, ...)
- `react-icons/md` — Material Design (MdEmail, MdStar, MdTrendingUp, ...)
- `react-icons/hi` — Heroicons (HiSparkles, HiChartBar, ...)
- `react-icons/bi` — Bootstrap Icons (BiTarget, BiRocket, ...)

アイコンの活用パターン:
- セクションヘッダーの横にアイコンを配置（カラー円背景 + 白アイコン）
- コンテンツカードの左上にアイコンを添える
- タイムラインやプロセスフローの各ステップにアイコンを付与
- 統計値の横にトレンドアイコン（FaArrowUp, FaChartLine 等）

カラー円背景 + 白アイコンのパターン:
```javascript
// 背景円
slide.addShape(pres.shapes.OVAL, {
  x: 1, y: 1, w: 0.7, h: 0.7, fill: { color: "0D9488" }
});
// 白アイコン（円の中央に配置）
const icon = await iconToBase64Png(FaCheckCircle, "FFFFFF", 256);
slide.addImage({ data: icon, x: 1.1, y: 1.1, w: 0.5, h: 0.5 });
```

【デザインのポイント】
- スキルの指示に含まれるデザインガイドラインに従ってください
- 単調なレイアウトの繰り返しを避け、スライドごとに異なるレイアウトを使用
- タイトルスライドはダーク背景、コンテンツスライドはライト背景が効果的
- 大きな数字（統計値など）は 60-72pt で目立たせる
- テキストだけのスライドは避け、必ずアイコンやシェイプなどのビジュアル要素を追加
- カードレイアウトにはシャドウ付き矩形 + アイコンの組み合わせが効果的
- グリッドレイアウト（2x2, 3x1 等）を活用し、各カードにアイコンを配置

【テンプレートからの編集】
テンプレートPPTXを編集する場合は、load_skill_resource で references/editing.md を読み込み、
XML編集ワークフローに従ってください。スクリプトの実行には run_skill_script を使います。

【結果の報告】
- PPTXファイルの生成が成功したら、プレゼンテーションの概要（スライド構成、ページ数など）を\
日本語で報告してください
- ダウンロードリンクやURLは絶対にテキストに含めないでください。\
ファイルは save_pptx_artifact / run_pptxgenjs の結果として自動的にユーザーに提供されます
- 「以下のリンクからダウンロード」のような案内は不要です
"""
