"""Chat API endpoint for the frontend."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from starlette.datastructures import UploadFile

from src.agents.pptx_agent import PPTX_ARTIFACT_MARKER, clear_pptx_thread_id, set_pptx_thread_id
from src.agents.root_agent import get_root_agent
from src.agents.tools.file_bridge import (
    get_request_files,
    set_request_files,
    store_attached_files,
)
from src.constants import APP_NAME, DEFAULT_USER_ID

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Create a session service (in production, use a persistent store)
session_service = InMemorySessionService()

# Gemini inline request limits
ALLOWED_MIME_TYPES = {
    # 画像
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
    # PDF
    "application/pdf",
    # PowerPoint
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # テキスト
    "text/plain",
    "text/html",
    "text/csv",
    # 音声
    "audio/wav",
    "audio/mp3",
    "audio/mpeg",
    "audio/ogg",
    "audio/webm",
    # 動画
    "video/mp4",
    "video/webm",
    "video/mpeg",
}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


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
        thread_id = str(form.get("threadId", "default"))
        user_id = str(form.get("userId", DEFAULT_USER_ID))

        parts: list[types.Part] = []
        if text.strip():
            parts.append(types.Part(text=text))

        # ファイル取得
        raw_files: list[dict] = []
        for key in form:
            value = form[key]
            if isinstance(value, UploadFile):
                mime_type = value.content_type or ""
                if mime_type not in ALLOWED_MIME_TYPES:
                    raise ValueError(f"サポートされていないファイル形式です: {mime_type}")

                file_bytes = await value.read()
                if len(file_bytes) > MAX_FILE_SIZE:
                    raise ValueError(
                        f"ファイルサイズが上限(20MB)を超えています: {value.filename}"
                    )

                # LLMコンテキスト用
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

    thread_id = body.get("threadId", "default")
    user_id = body.get("userId", DEFAULT_USER_ID)
    parts = [types.Part(text=last_message)]
    return parts, thread_id, user_id, {}


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


def _cleanup_request_stores() -> None:
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


@router.post("/chat")
async def chat_endpoint(request: Request) -> dict[str, Any]:
    """Chat completion endpoint for the frontend."""
    try:
        parts, thread_id, user_id, attached_files = await _parse_request(request)
    except (ValueError, Exception) as e:
        logger.error(f"Failed to parse request: {e}")
        return {"error": str(e)}

    root_agent = await get_root_agent(thread_id=thread_id)

    runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    await _get_or_create_session(user_id, thread_id)
    _setup_request_stores(thread_id, attached_files)

    content = types.Content(role="user", parts=parts)

    response_text = ""
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=thread_id,
            new_message=content,
        ):
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text
    except Exception as e:
        logger.error(f"Error running agent: {e}")
        response_text = f"エラーが発生しました: {str(e)}"
    finally:
        _cleanup_request_stores()

    return {
        "id": thread_id,
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text,
                },
                "finish_reason": "stop",
            }
        ],
    }


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
        _cleanup_request_stores()


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
