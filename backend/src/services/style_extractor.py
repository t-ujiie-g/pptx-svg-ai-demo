"""Style extraction service — single Gemini call returns Layer A + Layer B.

Inputs the cached `inspect_pptx` output (PNGs + structured shape info) and
emits a `StyleSpec` validated by Pydantic. Cached by source artifact id.

Why one call (not two): Layer A and Layer B reference the same slides; doing
them together keeps consistency (a template's fill_role keys back to the
palette in Layer A) and halves cost vs separate calls.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from google.genai import types as genai_types

from src.agents.style_schema import StyleSpec
from src.config import settings
from src.constants import (
    STYLE_EXTRACT_RAW_TEXT_PREVIEW_CHARS,
    STYLE_EXTRACT_TEXT_RUNS_PER_SHAPE,
)
from src.services.artifact_store import get_artifact
from src.services.genai_client import get_genai_client, with_genai_retry
from src.services.pptx_skill import inspect_pptx
from src.services.style_cache import get_cached_style, put_cached_style

logger = logging.getLogger(__name__)


_EXTRACTION_PROMPT = """\
あなたは PPTX のビジュアルデザインを抽出する専門家です。
添付された各スライドの PNG 画像と、シェイプ構造の要約を見て、
以下の JSON スキーマに沿った StyleSpec を生成してください。

## Layer A — 抽象スタイル
- palette: 主要色を6桁hex（'#'付き）で。primary/secondary/accent/bg_light/
  bg_dark/text_main/text_sub の7枠を必ず埋める。実際に多用されている色を
  優先し、足りない枠は調和する補色で埋める。dominance は最も視覚比率が
  大きい枠の名前。
- typography: ヘッダーフォントと本文フォントを分けて推定。size は実際の値
  （pt）。読み取れない場合はカテゴリの典型値（title=36, section=22, body=15,
  caption=11）にフォールバック。
- geometry: スライド全体のサイズと、外側余白・ブロック間ギャップの代表値
  を EMU で。
- decoration: 視覚モチーフ（rounded-cards / side-bar / icon-circles /
  thick-borders / gradient-bg / minimal / none）を1つ。
  uses_accent_lines は「タイトル下の細い装飾線」が使われていれば true。
- tone_tags: 見た目の雰囲気を最大5個の英単語で（executive, calm,
  technical, playful, premium, modern, formal, friendly 等）。

## Layer B — スライドテンプレート
**再利用に値するスライドのみ**を抽出してください。次の方針:

- cover (表紙): 1枚目が表紙なら必ず登録。タイトル/サブタイトル/装飾shape等
  をそれぞれ role 付きで列挙。
- closing (エンディング): 最終スライドが「ありがとうございました」などの
  典型エンディングなら登録。
- section_divider (章扉): 中扉スライドが存在すれば登録。
- agenda (目次): 目次スライドがあれば登録。
- content_two_col / content_grid / content_one_col / stat_callout /
  comparison / timeline: 本文ページの代表的レイアウトを最大2-3個まで。
  類似のページが多い場合は1枚を代表として登録すれば十分。

各 shape の text_template は具体テキストではなく、プレースホルダ:
  - タイトル → "<<TITLE>>"
  - サブタイトル → "<<SUBTITLE>>"
  - 本文段落 → "<<BODY_1>>", "<<BODY_2>>", ...
  - 箇条書き → "<<BULLET_1>>", "<<BULLET_2>>", ...
  - 数字 → "<<STAT_NUMBER>>"
  - 数字ラベル → "<<STAT_LABEL>>"
  - キャプション → "<<CAPTION>>"
  - その他テキスト → "<<TEXT_1>>", "<<TEXT_2>>", ...

二重中括弧 ({{ }}) は使わず、必ず "<<NAME>>" 形式で出力してください。

is_decoration=true な shape はテキストを持たない装飾図形（背景帯、
フッター帯、アクセント丸など）。fill_role は palette 上のどの色枠を使って
いるかを示す（具体hexは Layer A から引けばよい）。

x/y/cx/cy/rot は inspect の数値をそのまま使ってください（EMU、rotは60000分の1度）。
"""


def _build_inputs(info: dict[str, Any]) -> tuple[str, list[bytes]]:
    """Render a compact text summary + collect slide PNGs (decoded)."""
    lines = [
        f"スライド数: {info.get('slide_count', 0)}",
        f"サイズ: {info.get('slide_width_emu', 0)} x {info.get('slide_height_emu', 0)} EMU",
        "",
    ]
    pngs: list[bytes] = []
    for slide in info.get("slides", []):
        si = slide.get("slide_idx", 0)
        lines.append(f"--- スライド {si} ---")
        for shape in slide.get("shapes", []):
            idx = shape.get("idx", "?")
            stype = shape.get("shape_type", "?")
            x, y = shape.get("x", 0), shape.get("y", 0)
            cx, cy = shape.get("cx", 0), shape.get("cy", 0)
            fill = shape.get("fill_hex", "")
            line = (
                f"  shape[{idx}] type={stype} pos=({x},{y}) size=({cx},{cy})"
            )
            if fill:
                line += f" fill=#{fill}"
            lines.append(line)
            for tr in shape.get("text_runs", [])[:STYLE_EXTRACT_TEXT_RUNS_PER_SHAPE]:
                lines.append(f"    text: {tr['text']!r}")
        png_b64 = slide.get("png_base64")
        if png_b64:
            try:
                pngs.append(base64.b64decode(png_b64))
            except Exception as e:
                logger.warning(f"Failed to decode PNG for slide {si}: {e}")
    return "\n".join(lines), pngs


async def extract_style(
    artifact_id: str,
    *,
    use_cache: bool = True,
) -> StyleSpec:
    """Extract Layer A + Layer B style spec from a stored PPTX artifact.

    Caches by artifact id; pass `use_cache=False` to force re-extraction.
    Raises ValueError when the artifact isn't found, RuntimeError on LLM
    failure or schema-validation failure.
    """
    if use_cache:
        cached = get_cached_style(artifact_id)
        if cached is not None:
            logger.info(f"Style cache hit for artifact {artifact_id}")
            return cached

    artifact = get_artifact(artifact_id)
    if artifact is None:
        raise ValueError(f"Artifact not found: {artifact_id}")

    info = await inspect_pptx(artifact.data, with_png=True)
    structure_summary, pngs = _build_inputs(info)

    parts: list[genai_types.Part] = [
        genai_types.Part(text=_EXTRACTION_PROMPT),
        genai_types.Part(text="シェイプ構造の要約:\n" + structure_summary),
    ]
    for i, png in enumerate(pngs):
        parts.append(genai_types.Part(text=f"[スライド {i} の見た目]"))
        parts.append(genai_types.Part.from_bytes(data=png, mime_type="image/png"))

    model_id = settings.resolve_model(settings.agent_style_model)
    client = get_genai_client()
    logger.info(
        f"Extracting style for artifact {artifact_id} with model={model_id} "
        f"({len(pngs)} slides)"
    )

    try:
        response = await with_genai_retry(
            lambda: client.aio.models.generate_content(
                model=model_id,
                contents=genai_types.Content(role="user", parts=parts),
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=StyleSpec,
                ),
            ),
            label="style_extract",
        )
    except Exception as e:
        raise RuntimeError(f"Style extraction LLM call failed: {e}") from e

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, StyleSpec):
        spec = parsed
    else:
        # Fallback: parse response.text manually
        raw_text = getattr(response, "text", "") or ""
        if not raw_text:
            raise RuntimeError(
                "Style extraction returned no parsed object and no text"
            )
        try:
            spec = StyleSpec.model_validate_json(raw_text)
        except Exception as e:
            preview = raw_text[:STYLE_EXTRACT_RAW_TEXT_PREVIEW_CHARS]
            raise RuntimeError(
                f"Style extraction returned invalid JSON: {e}\n"
                f"raw[:{STYLE_EXTRACT_RAW_TEXT_PREVIEW_CHARS}]={preview!r}"
            ) from e

    put_cached_style(artifact_id, spec)
    return spec
