"""Chat API endpoint for the frontend."""

import base64
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from starlette.datastructures import UploadFile

from src.agents.pptx_agent import clear_pptx_thread_id, set_pptx_thread_id
from src.agents.root_agent import get_root_agent
from src.agents.tools.file_bridge import (
    get_request_files,
    set_request_files,
    store_attached_files,
)
from src.constants import (
    ALLOWED_UPLOAD_MIME_TYPES,
    APP_NAME,
    DEFAULT_ARTIFACT_FILENAME,
    DEFAULT_THREAD_ID,
    DEFAULT_USER_ID,
    MAX_UPLOAD_SIZE,
    PPTX_ARTIFACT_MARKER,
    PPTX_MIME_TYPE,
)
from src.services.artifact_store import get_artifact, store_artifact
from src.services.pptx_skill import inspect_pptx

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# In-memory session service. Acceptable for this demo; swap for a persistent
# store if multi-process deployment is introduced.
session_service = InMemorySessionService()

_MARKER_PREFIX = f"{PPTX_ARTIFACT_MARKER} "


def _extract_pptx_artifact(response: object) -> dict | None:
    """Find a `__PPTX_ARTIFACT__ {...}` line in a tool response's stdout.

    Returns the parsed artifact info dict, or None if the tool response
    doesn't carry one. Handles both direct dict responses and the nested
    `{"stdout": "..."}` shape that run_skill_script returns.
    """
    if not isinstance(response, dict):
        return None
    stdout = response.get("stdout", "")
    if not isinstance(stdout, str) or PPTX_ARTIFACT_MARKER not in stdout:
        return None
    for line in stdout.splitlines():
        if line.startswith(_MARKER_PREFIX):
            try:
                return json.loads(line[len(_MARKER_PREFIX):])
            except json.JSONDecodeError:
                return None
    return None


async def _build_pptx_context_parts(
    pptx_bytes: bytes, artifact_id: str,
) -> list[types.Part]:
    """Run pptx_inspect.js and return user-message Parts: text summary + PNG Parts.

    Returns a list of parts that should be appended to the user message so
    Gemini can see the current slide rendering plus structured shape info.
    """
    try:
        info = await inspect_pptx(pptx_bytes, with_png=True)
    except Exception as e:
        logger.error(f"PPTX inspect failed: {e}")
        return [types.Part(
            text=f"【添付PPTX（解析失敗）】artifact_id={artifact_id}\nエラー: {e}"
        )]

    lines = [
        f"【編集中PPTX — artifact_id: {artifact_id}】",
        f"スライド数: {info.get('slide_count', 0)}",
        f"スライドサイズ: {info.get('slide_width_emu', 0)} x "
        f"{info.get('slide_height_emu', 0)} EMU",
        "",
        "各スライドの見た目（PNG）とシェイプ構造を続けて添付します。",
        "編集するには pptx スキルの scripts/edit_pptx.py を run_skill_script 経由で使用してください。",
        f'artifact_id="{artifact_id}"',
        "",
    ]
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


async def _parse_request(
    request: Request,
) -> tuple[list[types.Part], str, str, dict[str, dict], list[dict]]:
    """JSONまたはmultipartリクエストをパースする。

    Returns:
        Tuple of (parts, thread_id, user_id, attached_files, uploaded_pptx_artifacts).
        uploaded_pptx_artifacts contains dicts with artifact_id/filename/size_bytes/download_url
        for each PPTX file uploaded in this request.

    Raises:
        ValueError: If the request body is invalid.
    """
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()

        # テキストフィールド取得
        text = str(form.get("text", ""))
        thread_id = str(form.get("threadId", DEFAULT_THREAD_ID))
        user_id = str(form.get("userId", DEFAULT_USER_ID))
        pptx_artifact_id = str(form.get("pptxArtifactId", ""))

        parts: list[types.Part] = []
        uploaded_pptx: list[dict] = []
        if text.strip():
            parts.append(types.Part(text=text))

        # pptx_artifact_id が指定されている場合、既存アーティファクトを
        # pptx_inspect.js で解析し、PNG + 構造情報を user message に付加
        if pptx_artifact_id:
            artifact = get_artifact(pptx_artifact_id)
            if artifact:
                logger.info(
                    f"Chat context using existing artifact {pptx_artifact_id} "
                    f"({len(artifact.data)} bytes, filename={artifact.filename})"
                )
                pptx_parts = await _build_pptx_context_parts(
                    artifact.data, pptx_artifact_id,
                )
                parts.extend(pptx_parts)
            else:
                logger.warning(
                    f"pptxArtifactId={pptx_artifact_id} not found in artifact store"
                )

        # ファイル取得
        raw_files: list[dict] = []
        for key in form:
            value = form[key]
            if isinstance(value, UploadFile):
                mime_type = value.content_type or ""
                if mime_type not in ALLOWED_UPLOAD_MIME_TYPES:
                    raise ValueError(f"サポートされていないファイル形式です: {mime_type}")

                file_bytes = await value.read()
                if len(file_bytes) > MAX_UPLOAD_SIZE:
                    limit_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
                    raise ValueError(
                        f"ファイルサイズが上限({limit_mb}MB)を超えています: {value.filename}"
                    )

                if mime_type == PPTX_MIME_TYPE:
                    # PPTX: アーティファクトに保存して pptx_inspect.js で解析、
                    # PNG + 構造情報を user message に付加
                    fname = value.filename or DEFAULT_ARTIFACT_FILENAME
                    aid = store_artifact(
                        thread_id=thread_id,
                        filename=fname,
                        data=file_bytes,
                    )
                    uploaded_pptx.append({
                        "artifact_id": aid,
                        "filename": fname,
                        "size_bytes": len(file_bytes),
                        "download_url": f"/artifacts/{aid}",
                    })
                    pptx_parts = await _build_pptx_context_parts(file_bytes, aid)
                    parts.extend(pptx_parts)
                else:
                    # 画像/PDF等はGeminiインラインパーツとして渡す
                    parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))

                # ファイルブリッジ用
                raw_files.append({
                    "file_name": value.filename or "unnamed",
                    "mime_type": mime_type,
                    "data_bytes": file_bytes,
                })

        if not parts:
            raise ValueError("テキストまたはファイルを入力してください")

        attached_files = store_attached_files(raw_files) if raw_files else {}
        return parts, thread_id, user_id, attached_files, uploaded_pptx

    # JSON リクエスト（従来互換）
    body = await request.json()
    messages = body.get("messages", [])
    if not messages:
        raise ValueError("No messages provided")

    last_message = _extract_last_user_message(messages)
    if not last_message:
        raise ValueError("No user message found")

    thread_id = body.get("threadId", DEFAULT_THREAD_ID)
    user_id = body.get("userId", DEFAULT_USER_ID)
    parts = [types.Part(text=last_message)]
    return parts, thread_id, user_id, {}, []


def _setup_request_stores(
    thread_id: str,
    attached_files: dict[str, dict] | None,
) -> None:
    """モジュールレベルストアにファイルをセットする。"""
    if attached_files:
        existing = get_request_files(thread_id)
        existing.update(attached_files)
        set_request_files(thread_id, existing)
    set_pptx_thread_id(thread_id)


async def _cleanup_request_stores(thread_id: str = "") -> None:
    """リクエストストアをクリーンアップする。"""
    clear_pptx_thread_id()


async def _get_or_create_session(user_id: str, thread_id: str):
    """ADK セッションを取得または新規作成する。"""
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=thread_id,
    )
    if session is None:
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=thread_id,
        )
    return session


def _extract_last_user_message(messages: list[dict]) -> str:
    """Extract the last user message from the messages list."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        return part.get("text", "")
                    elif isinstance(part, str):
                        return part
    return ""


async def _stream_agent_events(
    parts: list[types.Part],
    thread_id: str,
    user_id: str,
    attached_files: dict[str, dict] | None = None,
    uploaded_pptx: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream agent events as SSE format."""

    # アップロードされたPPTXがあれば、エージェント処理前に即座にプレビュー用イベントを送出
    for info in uploaded_pptx or []:
        pptx_event = {"type": "pptx_artifact", **info}
        yield f"data: {json.dumps(pptx_event, ensure_ascii=False)}\n\n"

    root_agent = await get_root_agent(thread_id=thread_id)

    runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    await _get_or_create_session(user_id, thread_id)
    _setup_request_stores(thread_id, attached_files)

    content = types.Content(role="user", parts=parts)

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=thread_id,
            new_message=content,
        ):
            # Check for function calls (tool invocation)
            if hasattr(event, "get_function_calls") and callable(event.get_function_calls):
                function_calls = event.get_function_calls()
                if function_calls:
                    for fc in function_calls:
                        tool_name = getattr(fc, "name", "unknown")
                        event_data = {
                            "type": "tool_call",
                            "tool": tool_name,
                            "status": "calling",
                        }
                        yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            # Check for function responses (tool results)
            if hasattr(event, "get_function_responses") and callable(event.get_function_responses):
                function_responses = event.get_function_responses()
                if function_responses:
                    for fr in function_responses:
                        tool_name = getattr(fr, "name", "unknown")

                        # Log skill script output for debugging
                        fr_response = getattr(fr, "response", None)
                        if isinstance(fr_response, dict) and "stdout" in fr_response:
                            stdout_text = fr_response["stdout"]
                            if stdout_text:
                                for line in stdout_text.splitlines():
                                    if not line.startswith(PPTX_ARTIFACT_MARKER):
                                        logger.info(f"Skill script [{tool_name}]: {line}")

                        # PPTX artifact marker detection — skill scripts
                        # (edit_pptx.py / generate_pptx.py) print a marker
                        # line on stdout that chat.py surfaces via SSE.
                        artifact_info = _extract_pptx_artifact(fr_response)
                        if artifact_info:
                            logger.info(
                                f"PPTX artifact detected for tool: {tool_name}"
                            )
                            pptx_event = {
                                "type": "pptx_artifact",
                                "artifact_id": artifact_info.get("artifact_id", ""),
                                "filename": artifact_info.get("filename", ""),
                                "size_bytes": artifact_info.get("size_bytes", 0),
                                "download_url": artifact_info.get("download_url", ""),
                            }
                            yield f"data: {json.dumps(pptx_event, ensure_ascii=False)}\n\n"

                        event_data = {
                            "type": "tool_result",
                            "tool": tool_name,
                            "status": "completed",
                        }
                        yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            # Check for text content
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        is_partial = getattr(event, "partial", False)
                        event_data = {
                            "type": "text_chunk" if is_partial else "text",
                            "content": part.text,
                        }
                        yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

        # Send completion event
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        logger.error(f"Error streaming agent events: {e}", exc_info=True)
        error_data = {"type": "error", "message": str(e)}
        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
    finally:
        await _cleanup_request_stores(thread_id)


@router.post("/chat/stream")
async def chat_stream_endpoint(request: Request) -> StreamingResponse:
    """Streaming chat endpoint using Server-Sent Events (SSE)."""
    try:
        parts, thread_id, user_id, attached_files, uploaded_pptx = await _parse_request(request)
    except (ValueError, Exception) as e:
        logger.error(f"Failed to parse request: {e}")
        error_gen = _error_generator(str(e))
        return StreamingResponse(error_gen, media_type="text/event-stream")

    return StreamingResponse(
        _stream_agent_events(parts, thread_id, user_id, attached_files, uploaded_pptx),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _error_generator(message: str) -> AsyncGenerator[str, None]:
    """Generate an error event for SSE."""
    yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
