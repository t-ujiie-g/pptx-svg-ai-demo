"""SSE event constants + payload builders for the chat stream.

All `type` values that the chat stream emits live here. Consolidating them
prevents typo drift between the chat.py emitter and the frontend consumer
(useChat.ts), and lets readers see the event vocabulary at a glance.

Frontend mirror: `frontend/src/hooks/useChat.ts` defines the same set on
`StreamEvent.type`. Keep in sync when adding new types.
"""

from __future__ import annotations

import json
from typing import Final

# ──────────────────────────────────────────────────────────────────────
# SSE event type names
# ──────────────────────────────────────────────────────────────────────

# Pipeline / mode (Phase 1-4.5)
EVENT_MODE_SPEC: Final = "mode_spec"
EVENT_STYLE_EXTRACTED: Final = "style_extracted"
EVENT_PRESERVATION: Final = "preservation"
EVENT_CRITIC_RESULT: Final = "critic_result"
EVENT_PIPELINE_STEP: Final = "pipeline_step"
EVENT_PAIRWISE_COMPARE: Final = "pairwise_compare"
EVENT_ROLLBACK: Final = "rollback"

# Tool / agent flow (existing)
EVENT_TOOL_CALL: Final = "tool_call"
EVENT_TOOL_RESULT: Final = "tool_result"
EVENT_TEXT: Final = "text"
EVENT_TEXT_CHUNK: Final = "text_chunk"
EVENT_PPTX_ARTIFACT: Final = "pptx_artifact"
EVENT_DONE: Final = "done"
EVENT_ERROR: Final = "error"

# Pipeline step names (sub-event for EVENT_PIPELINE_STEP)
PIPELINE_STEP_RETRY_START: Final = "retry_start"

# Status string used by SSE payloads where applicable
STATUS_COMPLETED: Final = "completed"
STATUS_FAILED: Final = "failed"


# ──────────────────────────────────────────────────────────────────────
# SSE wire-format helper
# ──────────────────────────────────────────────────────────────────────

def to_sse(payload: dict) -> str:
    """Serialize a dict payload as an SSE 'data:' line (with trailing blank).

    All chat SSE messages share this exact wire format. Centralizing it
    avoids subtle bugs (e.g., forgetting `ensure_ascii=False`).
    """
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ──────────────────────────────────────────────────────────────────────
# Payload builders (kept tiny — main use is to make call sites
# self-documenting and reduce inline literal repetition)
# ──────────────────────────────────────────────────────────────────────

def make_mode_spec_event(
    mode_spec_dump: dict,
    *,
    target_artifact_id: str | None,
    style_ref_artifact_id: str | None,
) -> dict:
    return {
        "type": EVENT_MODE_SPEC,
        "applied": mode_spec_dump,
        "target_artifact_id": target_artifact_id,
        "style_ref_artifact_id": style_ref_artifact_id,
    }


def make_pptx_artifact_event(info: dict) -> dict:
    """Normalize `info` (from skill stdout marker or upload metadata) to
    the SSE payload shape."""
    return {
        "type": EVENT_PPTX_ARTIFACT,
        "artifact_id": info.get("artifact_id", ""),
        "filename": info.get("filename", ""),
        "size_bytes": info.get("size_bytes", 0),
        "download_url": info.get("download_url", ""),
    }


def make_pipeline_step_event(step: str) -> dict:
    return {"type": EVENT_PIPELINE_STEP, "step": step}


def make_done_event() -> dict:
    return {"type": EVENT_DONE}


def make_error_event(message: str) -> dict:
    return {"type": EVENT_ERROR, "message": message}


def make_rollback_event(*, to_artifact_id: str, reason: str) -> dict:
    return {"type": EVENT_ROLLBACK, "to_artifact_id": to_artifact_id, "reason": reason}
