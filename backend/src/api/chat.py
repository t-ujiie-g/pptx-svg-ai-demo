"""Chat API endpoint — SSE stream orchestrating the agent + pipeline.

Layout (kept thin so the per-request wiring is easy to follow):
  - request parsing                  → `chat_request.parse_request`
  - SSE event vocabulary             → `chat_events`
  - post-generation pipeline helpers → `chat_pipeline`
  - this file: endpoint + the v1/v2 retry loop that ties everything together
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.agents.pptx_agent import clear_pptx_thread_id, set_pptx_thread_id
from src.agents.preservation_schema import PreservationScore
from src.agents.root_agent import get_root_agent
from src.agents.tools.file_bridge import (
    get_request_files,
    set_request_files,
)
from src.api.chat_events import (
    EVENT_TEXT,
    EVENT_TEXT_CHUNK,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    PIPELINE_STEP_RETRY_START,
    make_done_event,
    make_error_event,
    make_pipeline_step_event,
    make_pptx_artifact_event,
    make_rollback_event,
    to_sse,
)
from src.api.chat_pipeline import (
    build_retry_message,
    run_critic_review,
    run_pairwise_compare,
    run_preservation_check,
)
from src.api.chat_request import ParsedChatRequest, parse_request
from src.config import settings
from src.constants import (
    APP_NAME,
    CRITIC_MAX_RETRIES,
    PPTX_ARTIFACT_MARKER,
)
from src.services.artifact_store import get_artifact

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# In-memory session service. Acceptable for this demo; swap for a persistent
# store if multi-process deployment is introduced.
session_service = InMemorySessionService()

_MARKER_PREFIX = f"{PPTX_ARTIFACT_MARKER} "


# ──────────────────────────────────────────────────────────────────────
# ADK event → SSE adaptation
# ──────────────────────────────────────────────────────────────────────

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


def _emit_for_event(event: object) -> Iterator[tuple[str, str | None]]:
    """Convert one ADK event into one or more SSE strings.

    Yields `(sse_string, captured_artifact_id_or_none)`. The caller streams
    the strings and tracks the latest artifact id from the second element.
    Reused for both v1 and v2 (retry) loops so event-shape parsing isn't
    duplicated.
    """
    # Function calls (tool invocation start)
    if hasattr(event, "get_function_calls") and callable(event.get_function_calls):
        for fc in event.get_function_calls() or []:
            tool_name = getattr(fc, "name", "unknown")
            yield to_sse({
                "type": EVENT_TOOL_CALL, "tool": tool_name, "status": "calling",
            }), None

    # Function responses (tool result)
    if hasattr(event, "get_function_responses") and callable(event.get_function_responses):
        for fr in event.get_function_responses() or []:
            tool_name = getattr(fr, "name", "unknown")
            fr_response = getattr(fr, "response", None)

            # Log skill stdout (non-marker lines only) for debugging
            if isinstance(fr_response, dict) and "stdout" in fr_response:
                stdout_text = fr_response["stdout"]
                if stdout_text:
                    for line in stdout_text.splitlines():
                        if not line.startswith(PPTX_ARTIFACT_MARKER):
                            logger.info(f"Skill script [{tool_name}]: {line}")

            artifact_info = _extract_pptx_artifact(fr_response)
            captured_id: str | None = None
            if artifact_info:
                logger.info(f"PPTX artifact detected for tool: {tool_name}")
                captured_id = artifact_info.get("artifact_id") or None
                yield to_sse(make_pptx_artifact_event(artifact_info)), captured_id

            yield to_sse({
                "type": EVENT_TOOL_RESULT, "tool": tool_name, "status": "completed",
            }), None

    # Text content. `event.content.parts` may be None when the model returns
    # only function calls; guard against that to avoid `for ... in None`.
    if (
        hasattr(event, "content")
        and event.content
        and getattr(event.content, "parts", None)
    ):
        for part in event.content.parts:
            if hasattr(part, "text") and part.text:
                is_partial = getattr(event, "partial", False)
                yield to_sse({
                    "type": EVENT_TEXT_CHUNK if is_partial else EVENT_TEXT,
                    "content": part.text,
                }), None


# ──────────────────────────────────────────────────────────────────────
# Per-request stores (file_bridge + per-thread state)
# ──────────────────────────────────────────────────────────────────────

def _setup_request_stores(
    thread_id: str,
    attached_files: dict[str, dict] | None,
) -> None:
    if attached_files:
        existing = get_request_files(thread_id)
        existing.update(attached_files)
        set_request_files(thread_id, existing)
    set_pptx_thread_id(thread_id)


async def _cleanup_request_stores(thread_id: str = "") -> None:
    clear_pptx_thread_id()


async def _get_or_create_session(user_id: str, thread_id: str):
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=thread_id,
    )
    if session is None:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=thread_id,
        )
    return session


# ──────────────────────────────────────────────────────────────────────
# Streaming orchestrator
# ──────────────────────────────────────────────────────────────────────

async def _stream_agent_events(parsed: ParsedChatRequest) -> AsyncGenerator[str, None]:
    """Stream agent events as SSE format, then run the post-generation pipeline.

    Sequence:
      1. mode_spec / style_extracted / uploaded pptx — sent before the agent
      2. v1 agent run (streamed)
      3. v1 preservation + critic
      4. if verdict=retry: v2 agent run + v2 preservation + critic + pairwise
         + optional rollback
      5. done
    """
    # ── pre-agent SSE: mode + style + uploaded artifacts ───────────────
    yield to_sse(parsed.mode_spec_event)
    if parsed.style_event is not None:
        yield to_sse(parsed.style_event)
    for info in parsed.uploaded_pptx:
        yield to_sse({"type": "pptx_artifact", **info})

    intent = parsed.mode_spec.intent
    style_source_kind = parsed.mode_spec.style_source.kind

    runner = Runner(
        agent=await get_root_agent(thread_id=parsed.thread_id),
        app_name=APP_NAME,
        session_service=session_service,
    )
    await _get_or_create_session(parsed.user_id, parsed.thread_id)
    _setup_request_stores(parsed.thread_id, parsed.attached_files)

    final_output_artifact_id: str | None = None

    try:
        # ── v1: 初回エージェント実行 ───────────────────────────────────
        async for event in runner.run_async(
            user_id=parsed.user_id,
            session_id=parsed.thread_id,
            new_message=types.Content(role="user", parts=parsed.parts),
        ):
            for sse_str, captured_id in _emit_for_event(event):
                yield sse_str
                if captured_id:
                    final_output_artifact_id = captured_id

        v1_artifact_id = final_output_artifact_id

        # Phase 3: target 保全チェック (v1)
        preservation_score: PreservationScore | None = None
        if parsed.target_entities is not None and v1_artifact_id:
            preservation_event, preservation_score = await run_preservation_check(
                target=parsed.target_entities,
                output_artifact_id=v1_artifact_id,
                intent=intent,
            )
            yield to_sse(preservation_event)

        # Phase 4: Critic レビュー (v1) — feature flag で OFF にできる
        critic_v1_event: dict | None = None
        if v1_artifact_id and settings.feature_critic_review:
            critic_v1_event = await run_critic_review(
                output_artifact_id=v1_artifact_id,
                user_text=parsed.user_text,
                intent=intent,
                style_source_kind=style_source_kind,
                preservation=preservation_score,
            )
            yield to_sse(critic_v1_event)

        # Phase 4.5: verdict=retry なら 1 回だけ再生成して比較
        v1_verdict = (critic_v1_event or {}).get("result", {}).get("verdict")
        if (
            settings.feature_critic_retry
            and CRITIC_MAX_RETRIES > 0
            and v1_artifact_id
            and v1_verdict == "retry"
        ):
            async for sse in _run_retry_loop(
                runner=runner,
                parsed=parsed,
                v1_artifact_id=v1_artifact_id,
                critic_v1_event=critic_v1_event or {},
                preservation_score_v1=preservation_score,
            ):
                yield sse

        yield to_sse(make_done_event())

    except Exception as e:
        logger.error(f"Error streaming agent events: {e}", exc_info=True)
        yield to_sse(make_error_event(str(e)))
    finally:
        await _cleanup_request_stores(parsed.thread_id)


async def _run_retry_loop(
    *,
    runner: Runner,
    parsed: ParsedChatRequest,
    v1_artifact_id: str,
    critic_v1_event: dict,
    preservation_score_v1: PreservationScore | None,
) -> AsyncGenerator[str, None]:
    """Phase 4.5: stream the v2 retry, then pairwise + optional rollback."""
    yield to_sse(make_pipeline_step_event(PIPELINE_STEP_RETRY_START))

    retry_content = build_retry_message(
        critic_result=critic_v1_event,
        preservation_score=preservation_score_v1,
    )

    v2_artifact_id: str | None = None
    async for event in runner.run_async(
        user_id=parsed.user_id,
        session_id=parsed.thread_id,
        new_message=retry_content,
    ):
        for sse_str, captured_id in _emit_for_event(event):
            yield sse_str
            if captured_id:
                v2_artifact_id = captured_id

    if v2_artifact_id is None:
        logger.info("Retry produced no new artifact; keeping v1")
        return
    if v2_artifact_id == v1_artifact_id:
        return

    intent = parsed.mode_spec.intent
    style_source_kind = parsed.mode_spec.style_source.kind

    # v2 の preservation + critic
    preservation_score_v2: PreservationScore | None = None
    if parsed.target_entities is not None:
        preservation_event_v2, preservation_score_v2 = await run_preservation_check(
            target=parsed.target_entities,
            output_artifact_id=v2_artifact_id,
            intent=intent,
        )
        yield to_sse(preservation_event_v2)

    critic_v2_event = await run_critic_review(
        output_artifact_id=v2_artifact_id,
        user_text=parsed.user_text,
        intent=intent,
        style_source_kind=style_source_kind,
        preservation=preservation_score_v2,
    )
    yield to_sse(critic_v2_event)

    # ペアワイズ比較で勝者を決定
    weighted_v1 = critic_v1_event.get("result", {}).get("weighted")
    weighted_v2 = critic_v2_event.get("result", {}).get("weighted")
    pairwise_event, winner_id = await run_pairwise_compare(
        v1_artifact_id=v1_artifact_id,
        v2_artifact_id=v2_artifact_id,
        user_text=parsed.user_text,
        intent=intent,
        weighted_v1=weighted_v1,
        weighted_v2=weighted_v2,
    )
    yield to_sse(pairwise_event)

    # v1 が勝者なら rollback: フロントは v1 をアクティブに戻す
    if winner_id == v1_artifact_id:
        yield to_sse(make_rollback_event(
            to_artifact_id=v1_artifact_id,
            reason="pairwise: v1 was preferred over v2",
        ))
        # フロントは latest pptx_artifact を表示するので、v1 を再送して preview を戻す
        v1_artifact = get_artifact(v1_artifact_id)
        if v1_artifact:
            yield to_sse(make_pptx_artifact_event({
                "artifact_id": v1_artifact_id,
                "filename": v1_artifact.filename,
                "size_bytes": len(v1_artifact.data),
                "download_url": f"/artifacts/{v1_artifact_id}",
            }))


# ──────────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────────

@router.post("/chat/stream")
async def chat_stream_endpoint(request: Request) -> StreamingResponse:
    """Streaming chat endpoint using Server-Sent Events (SSE)."""
    try:
        parsed = await parse_request(request)
    except (ValueError, Exception) as e:
        logger.error(f"Failed to parse request: {e}")
        return StreamingResponse(
            _error_generator(str(e)), media_type="text/event-stream",
        )

    return StreamingResponse(
        _stream_agent_events(parsed),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _error_generator(message: str) -> AsyncGenerator[str, None]:
    yield to_sse(make_error_event(message))
