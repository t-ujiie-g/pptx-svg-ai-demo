"""Chat API endpoint for the frontend."""

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from starlette.datastructures import UploadFile

from src.agents.pptx_agent import (
    PPTX_ARTIFACT_MARKER,
    clear_edit_session,
    clear_pptx_thread_id,
    set_edit_session,
    set_pptx_thread_id,
)
from src.agents.root_agent import get_root_agent
from src.agents.tools.file_bridge import (
    get_request_files,
    set_request_files,
    store_attached_files,
)
from src.constants import (
    ALLOWED_UPLOAD_MIME_TYPES,
    APP_NAME,
    DEFAULT_THREAD_ID,
    DEFAULT_USER_ID,
    MAX_UPLOAD_SIZE,
    PPTX_MIME_TYPE,
)
from src.services.artifact_store import get_artifact, store_artifact
from src.services.pptx_edit_bridge import bridge

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# In-memory session service. Acceptable for this demo; swap for a persistent
# store if multi-process deployment is introduced.
session_service = InMemorySessionService()


async def _extract_pptx_context_via_bridge(
    pptx_bytes: bytes, session_id: str, artifact_id: str,
) -> str:
    """Load PPTX into bridge and return structured shape info as text context."""
    try:
        await bridge.load_pptx(session_id, pptx_bytes)
        info = await bridge.get_all_slides_info(session_id)
        set_edit_session(session_id)

        lines = [
            f"【編集中PPTX — artifact_id: {artifact_id}】",
            f"スライド数: {info.get('slide_count', 0)}",
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
                parts_desc = f"  shape[{idx}] type={stype} pos=({x},{y}) size=({cx},{cy})"
                if fill:
                    parts_desc += f" fill=#{fill}"
                lines.append(parts_desc)
                for tr in shape.get("text_runs", []):
                    lines.append(f"    text[p{tr['pi']},r{tr['ri']}]: {tr['text']!r}")
            lines.append("")

        lines.append(
            "※ 上記PPTXを編集するには load_pptx → edit_shape_* → save_edited_pptx を使用してください。"
            f" artifact_id=\"{artifact_id}\""
        )
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Bridge PPTX context extraction failed: {e}")
        return f"【添付PPTX（解析失敗）】artifact_id={artifact_id}\nエラー: {e}"


async def _parse_request(
    request: Request,
) -> tuple[list[types.Part], str, str, dict[str, dict]]:
    """JSONまたはmultipartリクエストをパースする。

    Returns:
        Tuple of (parts, thread_id, user_id, attached_files).

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
        if text.strip():
            parts.append(types.Part(text=text))

        # pptx_artifact_id が指定されている場合、既存アーティファクトからブリッジ経由でコンテキスト生成
        if pptx_artifact_id:
            artifact = get_artifact(pptx_artifact_id)
            if artifact:
                ctx = await _extract_pptx_context_via_bridge(
                    artifact.data, threadId_to_session(thread_id), pptx_artifact_id,
                )
                parts.append(types.Part(text=ctx))

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
                    # PPTX: アーティファクトに保存してブリッジ経由でコンテキスト生成
                    aid = store_artifact(
                        thread_id=thread_id,
                        filename=value.filename or "presentation.pptx",
                        data=file_bytes,
                    )
                    ctx = await _extract_pptx_context_via_bridge(
                        file_bytes, threadId_to_session(thread_id), aid,
                    )
                    parts.append(types.Part(text=ctx))
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
        return parts, thread_id, user_id, attached_files

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
    return parts, thread_id, user_id, {}


def threadId_to_session(thread_id: str) -> str:
    """Convert thread_id to bridge session_id."""
    return f"edit-{thread_id}"


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
    clear_edit_session()
    # ブリッジセッションのアンロードはしない（同一スレッドで再利用可能にするため）


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
) -> AsyncGenerator[str, None]:
    """Stream agent events as SSE format."""
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

                        # PPTX artifact marker detection
                        response_data = getattr(fr, "response", {})
                        if isinstance(response_data, dict) and response_data.get(
                            PPTX_ARTIFACT_MARKER
                        ):
                            logger.info(
                                f"PPTX artifact detected for tool: {tool_name}"
                            )
                            pptx_event = {
                                "type": "pptx_artifact",
                                "artifact_id": response_data.get("artifact_id", ""),
                                "filename": response_data.get("filename", ""),
                                "size_bytes": response_data.get("size_bytes", 0),
                                "download_url": response_data.get("download_url", ""),
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
        parts, thread_id, user_id, attached_files = await _parse_request(request)
    except (ValueError, Exception) as e:
        logger.error(f"Failed to parse request: {e}")
        error_gen = _error_generator(str(e))
        return StreamingResponse(error_gen, media_type="text/event-stream")

    return StreamingResponse(
        _stream_agent_events(parts, thread_id, user_id, attached_files),
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
