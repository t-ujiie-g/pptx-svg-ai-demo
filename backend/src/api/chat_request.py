"""Chat request parsing — multipart and legacy JSON.

The chat endpoint accepts two shapes:
  - **multipart/form-data**: text + attachments + mode_spec + style_ref upload
    (the modern frontend path)
  - **JSON**: legacy fallback with just message history

Both produce a `ParsedChatRequest` NamedTuple consumed by `chat.py`. Keeping
this in its own module keeps `chat.py` focused on streaming/orchestration.
"""

from __future__ import annotations

import base64
import logging
from typing import NamedTuple

from fastapi import Request
from google.genai import types
from starlette.datastructures import FormData, UploadFile

from src.agents.mode import ModeSpec, infer_mode_spec, parse_mode_spec
from src.agents.preservation_schema import EntitySet
from src.agents.tools.file_bridge import store_attached_files
from src.api.chat_events import make_mode_spec_event
from src.api.chat_pipeline import maybe_extract_style, maybe_extract_target_entities
from src.constants import (
    ALLOWED_UPLOAD_MIME_TYPES,
    DEFAULT_ARTIFACT_FILENAME,
    DEFAULT_THREAD_ID,
    DEFAULT_USER_ID,
    MAX_UPLOAD_SIZE,
    PPTX_MIME_TYPE,
    PPTX_ROLE_STYLE_REF,
    PPTX_ROLE_TARGET,
    STYLE_REF_DEFAULT_FILENAME,
    PptxContextRole,
)
from src.services.artifact_store import get_artifact, store_artifact
from src.services.pptx_skill import inspect_pptx

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# ParsedChatRequest — bundle handed to the SSE streamer
# ──────────────────────────────────────────────────────────────────────

class ParsedChatRequest(NamedTuple):
    """Per-request state needed by `_stream_agent_events`.

    Built by `parse_request` and consumed by the streaming layer. Using a
    NamedTuple keeps the long return type readable and lets call sites
    destructure by name when they only need a subset.
    """

    parts: list[types.Part]
    thread_id: str
    user_id: str
    attached_files: dict[str, dict]
    uploaded_pptx: list[dict]
    mode_spec: ModeSpec
    mode_spec_event: dict
    style_event: dict | None
    # Phase 3: target entity set captured pre-generation. Compared against
    # the agent's output post-generation to compute the preservation score.
    # None when intent doesn't require preservation (tweak / from-scratch).
    target_entities: EntitySet | None
    # Phase 4: original user prompt text — passed to the critic so it can
    # score `intent_fit`. The agent already saw this; we just need to keep
    # it accessible separately from the (longer) list of mixed-content parts.
    user_text: str


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _validate_upload_size(file_bytes: bytes, label: str) -> None:
    """Reject uploads larger than MAX_UPLOAD_SIZE with a Japanese error message."""
    if len(file_bytes) <= MAX_UPLOAD_SIZE:
        return
    limit_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
    raise ValueError(f"{label}のサイズが上限({limit_mb}MB)を超えています")


async def build_pptx_context_parts(
    pptx_bytes: bytes,
    artifact_id: str,
    *,
    role: PptxContextRole = PPTX_ROLE_TARGET,
) -> list[types.Part]:
    """Run pptx_inspect.js and return user-message Parts: text summary + PNG Parts.

    `role` distinguishes the artifact's purpose in the prompt:
      - "target":    現在編集中のPPTX (intent ∈ {tweak, polish} の編集対象)
      - "style_ref": 参照スタイル用のPPTX (編集対象ではない)
    """
    try:
        info = await inspect_pptx(pptx_bytes, with_png=True)
    except Exception as e:
        logger.error(f"PPTX inspect failed: {e}")
        return [types.Part(
            text=f"【添付PPTX(解析失敗)】role={role} artifact_id={artifact_id}\nエラー: {e}"
        )]

    if role == PPTX_ROLE_STYLE_REF:
        lines = [
            f"【参照スタイルPPTX — artifact_id: {artifact_id}】",
            "このPPTXは「スタイル参照用」です。直接編集しないでください。",
            "配色・フォント・余白・装飾の傾向や、テンプレート的に再利用できる",
            "スライド(表紙・章扉・エンディング等)を読み取って、生成や編集の参考に",
            "してください。",
        ]
    else:
        lines = [
            f"【編集中PPTX — artifact_id: {artifact_id}】",
            "編集するには pptx スキルの scripts/edit_pptx.py を",
            "run_skill_script 経由で使用してください。",
            f'artifact_id="{artifact_id}"',
        ]
    lines += [
        f"スライド数: {info.get('slide_count', 0)}",
        f"スライドサイズ: {info.get('slide_width_emu', 0)} x "
        f"{info.get('slide_height_emu', 0)} EMU",
        "",
        "各スライドの見た目(PNG)とシェイプ構造を続けて添付します。",
        "",
    ]
    # スライド寸法。シェイプ座標を「スライド比%」に正規化して LLM のはみ出し
    # 判断を助ける（pptx-skill の percent-coordinate モデルの取り込み）。
    sw = info.get("slide_width_emu", 0) or 0
    sh = info.get("slide_height_emu", 0) or 0
    for slide in info.get("slides", []):
        si = slide.get("slide_idx", 0)
        lines.append(f"--- スライド {si} ---")
        for shape in slide.get("shapes", []):
            idx = shape.get("idx", "?")
            stype = shape.get("shape_type", "?")
            x, y = shape.get("x", 0), shape.get("y", 0)
            cx, cy = shape.get("cx", 0), shape.get("cy", 0)
            fill = shape.get("fill_hex", "")
            rot = shape.get("rot", 0)
            desc = (
                f"  shape[{idx}] type={stype} "
                f"pos=({x},{y}) size=({cx},{cy}) rot={rot}"
            )
            if sw and sh:
                desc += (
                    f" ≈pos({x / sw * 100:.0f}%,{y / sh * 100:.0f}%)"
                    f" size({cx / sw * 100:.0f}%x{cy / sh * 100:.0f}%)"
                )
                # スライド枠を超える配置は overflow として明示（Critic の減点軸）。
                if x < 0 or y < 0 or x + cx > sw or y + cy > sh:
                    desc += " ⚠overflow"
            if fill:
                desc += f" fill=#{fill}"
            lines.append(desc)
            for tr in shape.get("text_runs", []):
                lines.append(f"    text[p{tr['pi']},r{tr['ri']}]: {tr['text']!r}")
            tbl = shape.get("table")
            if tbl:
                lines.append(
                    f"    table rows={tbl.get('rows', 0)} cols={tbl.get('cols', 0)}"
                )
                for r, row in enumerate(tbl.get("cells", [])):
                    for c, cell in enumerate(row):
                        suffix = ""
                        if cell.get("fill_hex"):
                            suffix = f" fill=#{cell['fill_hex']}"
                        text = cell.get("text", "")
                        lines.append(f"      cell[{r},{c}]{suffix}: {text!r}")
        lines.append("")

    parts: list[types.Part] = [types.Part(text="\n".join(lines))]
    for slide in info.get("slides", []):
        png_b64 = slide.get("png_base64")
        if not png_b64:
            continue
        parts.append(types.Part(text=f"[スライド {slide.get('slide_idx', 0)} の見た目]"))
        parts.append(types.Part.from_bytes(
            data=base64.b64decode(png_b64),
            mime_type="image/png",
        ))
    return parts


async def _store_style_ref_upload(
    style_ref_file: UploadFile, thread_id: str,
) -> str:
    """Validate + persist a styleRefFile upload, return its artifact id."""
    mime_type = style_ref_file.content_type or ""
    if mime_type != PPTX_MIME_TYPE:
        raise ValueError(
            f"参照スタイルファイルは PPTX のみ受け付けます (mime: {mime_type})"
        )
    ref_bytes = await style_ref_file.read()
    _validate_upload_size(ref_bytes, "参照スタイル PPTX")
    ref_fname = style_ref_file.filename or STYLE_REF_DEFAULT_FILENAME
    artifact_id = store_artifact(
        thread_id=thread_id, filename=ref_fname, data=ref_bytes,
    )
    logger.info(
        f"Stored style_ref upload as artifact {artifact_id} "
        f"({len(ref_bytes)} bytes, filename={ref_fname})"
    )
    return artifact_id


def _resolve_mode_spec(
    *,
    raw_mode_spec: str | None,
    text: str,
    target_artifact_id: str | None,
    style_ref_artifact_id: str | None,
) -> ModeSpec:
    """Pick the user-supplied modeSpec if present, otherwise infer one.

    Always validates the result against the available artifact ids.
    """
    user_provided = parse_mode_spec(raw_mode_spec)
    spec = user_provided or infer_mode_spec(
        text=text,
        target_artifact_id=target_artifact_id,
        style_ref_artifact_id=style_ref_artifact_id,
    )
    spec.validate_against_inputs(
        target_artifact_id=target_artifact_id,
        style_ref_artifact_id=style_ref_artifact_id,
    )
    return spec


async def _append_existing_pptx_context(
    *,
    parts: list[types.Part],
    artifact_id: str,
    role: PptxContextRole,
    role_label_for_log: str,
) -> None:
    """Look up an existing artifact and append its inspect output to `parts`."""
    artifact = get_artifact(artifact_id)
    if artifact is None:
        logger.warning(f"{role_label_for_log}={artifact_id} not found in artifact store")
        return
    logger.info(
        f"Chat context using {role_label_for_log} {artifact_id} "
        f"({len(artifact.data)} bytes, filename={artifact.filename})"
    )
    parts.extend(
        await build_pptx_context_parts(artifact.data, artifact_id, role=role)
    )


async def _consume_attachments(
    *,
    form: FormData,
    thread_id: str,
    parts: list[types.Part],
) -> tuple[list[dict], list[dict]]:
    """Iterate non-styleRefFile UploadFiles, attach to parts, return raw + uploaded_pptx."""
    raw_files: list[dict] = []
    uploaded_pptx: list[dict] = []

    for key in form:
        # styleRefFile は事前処理済みなのでスキップ
        if key == "styleRefFile":
            continue
        value = form[key]
        if not isinstance(value, UploadFile):
            continue

        mime_type = value.content_type or ""
        if mime_type not in ALLOWED_UPLOAD_MIME_TYPES:
            raise ValueError(f"サポートされていないファイル形式です: {mime_type}")

        file_bytes = await value.read()
        _validate_upload_size(file_bytes, f"ファイル({value.filename})")

        if mime_type == PPTX_MIME_TYPE:
            fname = value.filename or DEFAULT_ARTIFACT_FILENAME
            aid = store_artifact(thread_id=thread_id, filename=fname, data=file_bytes)
            uploaded_pptx.append({
                "artifact_id": aid,
                "filename": fname,
                "size_bytes": len(file_bytes),
                "download_url": f"/artifacts/{aid}",
            })
            parts.extend(
                await build_pptx_context_parts(file_bytes, aid, role=PPTX_ROLE_TARGET)
            )
        else:
            # 画像/PDF等は Gemini のインラインパーツとして渡す
            parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))

        raw_files.append({
            "file_name": value.filename or "unnamed",
            "mime_type": mime_type,
            "data_bytes": file_bytes,
        })

    return raw_files, uploaded_pptx


def _extract_last_user_message(messages: list[dict]) -> str:
    """Extract the last user message from the legacy JSON request shape."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        return part.get("text", "")
                    if isinstance(part, str):
                        return part
    return ""


# ──────────────────────────────────────────────────────────────────────
# Top-level parsers
# ──────────────────────────────────────────────────────────────────────

async def _parse_multipart_request(form: FormData) -> ParsedChatRequest:
    """Parse a multipart/form-data chat request."""
    text = str(form.get("text", ""))
    thread_id = str(form.get("threadId", DEFAULT_THREAD_ID))
    user_id = str(form.get("userId", DEFAULT_USER_ID))
    pptx_artifact_id = str(form.get("pptxArtifactId", "")) or None
    style_ref_artifact_id = str(form.get("styleRefArtifactId", "")) or None
    raw_mode_spec = form.get("modeSpec")
    raw_mode_spec_str = str(raw_mode_spec) if raw_mode_spec is not None else None

    # styleRefFile が直接アップロードされていれば、先に保存して
    # style_ref_artifact_id を確定する(後段ループでは二重処理しない)。
    style_ref_file_obj = form.get("styleRefFile")
    if isinstance(style_ref_file_obj, UploadFile):
        style_ref_artifact_id = await _store_style_ref_upload(
            style_ref_file_obj, thread_id,
        )

    mode_spec = _resolve_mode_spec(
        raw_mode_spec=raw_mode_spec_str,
        text=text,
        target_artifact_id=pptx_artifact_id,
        style_ref_artifact_id=style_ref_artifact_id,
    )

    parts: list[types.Part] = [
        types.Part(text=mode_spec.to_instruction_block(
            target_artifact_id=pptx_artifact_id,
            style_ref_artifact_id=style_ref_artifact_id,
        )),
    ]
    if text.strip():
        parts.append(types.Part(text=text))

    if pptx_artifact_id:
        await _append_existing_pptx_context(
            parts=parts,
            artifact_id=pptx_artifact_id,
            role=PPTX_ROLE_TARGET,
            role_label_for_log="pptxArtifactId",
        )
    if style_ref_artifact_id:
        await _append_existing_pptx_context(
            parts=parts,
            artifact_id=style_ref_artifact_id,
            role=PPTX_ROLE_STYLE_REF,
            role_label_for_log="styleRefArtifactId",
        )

    mode_spec_event = make_mode_spec_event(
        mode_spec.model_dump(),
        target_artifact_id=pptx_artifact_id,
        style_ref_artifact_id=style_ref_artifact_id,
    )

    raw_files, uploaded_pptx = await _consume_attachments(
        form=form, thread_id=thread_id, parts=parts,
    )

    # mode_spec ブロックが先頭に必ず入っているので、それ以外の入力ゼロは弾く
    has_user_content = bool(
        text.strip() or raw_files or pptx_artifact_id or style_ref_artifact_id
    )
    if not has_user_content:
        raise ValueError("テキストまたはファイルを入力してください")

    # Phase 2: Layer A+B 抽出 (失敗してもリクエストは止めない)
    style_event = await maybe_extract_style(
        mode_spec=mode_spec,
        target_artifact_id=pptx_artifact_id,
        style_ref_artifact_id=style_ref_artifact_id,
        parts=parts,
    )

    # Phase 3: polish/restructure のとき target からエンティティ抽出
    target_entities = await maybe_extract_target_entities(
        mode_spec=mode_spec,
        target_artifact_id=pptx_artifact_id,
        parts=parts,
    )

    attached_files = store_attached_files(raw_files) if raw_files else {}
    return ParsedChatRequest(
        parts=parts,
        thread_id=thread_id,
        user_id=user_id,
        attached_files=attached_files,
        uploaded_pptx=uploaded_pptx,
        mode_spec=mode_spec,
        mode_spec_event=mode_spec_event,
        style_event=style_event,
        target_entities=target_entities,
        user_text=text,
    )


def _parse_json_request(body: dict) -> ParsedChatRequest:
    """Parse the legacy JSON chat request shape (no artifacts, no mode UI)."""
    messages = body.get("messages", [])
    if not messages:
        raise ValueError("No messages provided")

    last_message = _extract_last_user_message(messages)
    if not last_message:
        raise ValueError("No user message found")

    thread_id = body.get("threadId", DEFAULT_THREAD_ID)
    user_id = body.get("userId", DEFAULT_USER_ID)
    # JSON ルート: target/style_ref が無いので必ず from-scratch に倒れる
    mode_spec = infer_mode_spec(
        text=last_message, target_artifact_id=None, style_ref_artifact_id=None,
    )
    parts = [
        types.Part(text=mode_spec.to_instruction_block(
            target_artifact_id=None, style_ref_artifact_id=None,
        )),
        types.Part(text=last_message),
    ]
    mode_spec_event = make_mode_spec_event(
        mode_spec.model_dump(),
        target_artifact_id=None,
        style_ref_artifact_id=None,
    )
    return ParsedChatRequest(
        parts=parts,
        thread_id=thread_id,
        user_id=user_id,
        attached_files={},
        uploaded_pptx=[],
        mode_spec=mode_spec,
        mode_spec_event=mode_spec_event,
        style_event=None,
        target_entities=None,
        user_text=last_message,
    )


async def parse_request(request: Request) -> ParsedChatRequest:
    """Parse a chat request (multipart or JSON) into the SSE input bundle.

    Raises:
        ValueError: when the request body is malformed or violates a constraint.
    """
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        return await _parse_multipart_request(await request.form())
    return _parse_json_request(await request.json())
