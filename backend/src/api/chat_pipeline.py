"""Chat pipeline post-processing helpers (Phase 2-4.5).

Pure-ish functions that the chat SSE stream calls between agent runs:
  - `maybe_extract_style`        Phase 2: extract Layer A+B style spec
  - `maybe_extract_target_entities` / `render_entity_preservation_block`  Phase 3
  - `run_preservation_check`     Phase 3: post-generation entity comparison
  - `run_critic_review`          Phase 4: independent quality review
  - `run_pairwise_compare`       Phase 4.5: v1 vs v2 winner judgement
  - `build_retry_message`        Phase 4.5: continuation prompt for v2

Each returns an SSE event payload (dict) that the caller serializes via
`chat_events.to_sse`. Keeping these out of `chat.py` keeps the streaming
orchestrator under ~400 lines and lets the helpers be unit-tested in isolation.
"""

from __future__ import annotations

import logging

from google.genai import types

from src.agents.mode import ModeSpec
from src.agents.preservation_schema import EntitySet, PreservationScore
from src.agents.style_schema import StyleSpec
from src.api.chat_events import (
    EVENT_CRITIC_RESULT,
    EVENT_PAIRWISE_COMPARE,
    EVENT_PRESERVATION,
    EVENT_STYLE_EXTRACTED,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
from src.config import settings
from src.constants import (
    ENTITY_BLOCK_MAX_ITEMS,
    PAIRWISE_TIE_BREAK_MARGIN,
    PPTX_ROLE_STYLE_REF,
    PPTX_ROLE_TARGET,
    PptxContextRole,
)
from src.services.critic import compare_pairwise, decide_winner, run_critic
from src.services.entity_extractor import extract_entities
from src.services.preservation import compute_preservation_score, threshold_for_intent
from src.services.style_extractor import extract_style

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Phase 2 — Style extraction
# ──────────────────────────────────────────────────────────────────────

async def maybe_extract_style(
    *,
    mode_spec: ModeSpec,
    target_artifact_id: str | None,
    style_ref_artifact_id: str | None,
    parts: list[types.Part],
) -> dict | None:
    """Run Layer A+B style extraction when mode_spec calls for it.

    Mutates `parts` to append a compact StyleSpec instruction block when
    extraction succeeds. Returns the SSE event payload (or None if no
    extraction happened or the feature flag is off).
    """
    if not settings.feature_style_extraction:
        return None
    kind = mode_spec.style_source.kind
    source_id: str
    role: PptxContextRole
    if kind == "from-target" and target_artifact_id:
        source_id, role = target_artifact_id, PPTX_ROLE_TARGET
    elif kind in ("from-ref", "mix") and style_ref_artifact_id:
        source_id, role = style_ref_artifact_id, PPTX_ROLE_STYLE_REF
    else:
        return None  # preset only or no source artifact

    try:
        spec: StyleSpec = await extract_style(source_id)
    except Exception as e:
        logger.warning(f"Style extraction skipped: {e}")
        return {
            "type": EVENT_STYLE_EXTRACTED,
            "status": STATUS_FAILED,
            "source_artifact_id": source_id,
            "role": role,
            "error": str(e),
        }

    parts.append(types.Part(
        text=spec.to_compact_block(source_artifact_id=source_id, role=role),
    ))
    return {
        "type": EVENT_STYLE_EXTRACTED,
        "status": STATUS_COMPLETED,
        "source_artifact_id": source_id,
        "role": role,
        "summary": {
            "palette": spec.layer_a.palette.model_dump(),
            "header_font": spec.layer_a.typography.header_font,
            "body_font": spec.layer_a.typography.body_font,
            "tone_tags": spec.layer_a.tone_tags,
            "template_kinds": [t.kind for t in spec.layer_b.slides],
        },
    }


# ──────────────────────────────────────────────────────────────────────
# Phase 3 — Pre-generation entity capture & post-generation preservation
# ──────────────────────────────────────────────────────────────────────

async def maybe_extract_target_entities(
    *,
    mode_spec: ModeSpec,
    target_artifact_id: str | None,
    parts: list[types.Part],
) -> EntitySet | None:
    """Extract entities from the target PPTX before generation.

    Only runs when intent requires a preservation check (`polish` /
    `restructure`). Mutates `parts` to add a "保全すべき情報" block listing
    the top entities so the agent knows what to keep. Returns the EntitySet
    so the caller can compare it against the output post-generation.
    """
    if not settings.feature_preservation_check:
        return None
    if threshold_for_intent(mode_spec.intent) is None:
        return None
    if not target_artifact_id:
        return None

    try:
        entities = await extract_entities(target_artifact_id)
    except Exception as e:
        logger.warning(f"Target entity extraction skipped: {e}")
        return None

    parts.append(types.Part(text=render_entity_preservation_block(
        entities=entities, intent=mode_spec.intent,
    )))
    return entities


def render_entity_preservation_block(
    *,
    entities: EntitySet,
    intent: str,
) -> str:
    """Render the preservation hint block injected into the user message."""
    threshold = threshold_for_intent(intent) or 0.0
    lines = [
        "【保全すべき情報】",
        f"intent={intent}, threshold={threshold:.2f}",
        "以下のエンティティは target から抽出済みです。生成・編集後のスライドに",
        "これらが残るようにしてください。失うと preservation_check が失敗します。",
        "",
    ]
    if not entities.entities:
        lines.append("(対象なし — target にエンティティ無し)")
        return "\n".join(lines)

    shown = entities.entities[:ENTITY_BLOCK_MAX_ITEMS]
    for ent in shown:
        lines.append(f"- [{ent.type}] {ent.value}  (slide {ent.slide_idx})")
    remaining = len(entities.entities) - len(shown)
    if remaining > 0:
        lines.append(f"... 他 {remaining} 件 (省略)")
    return "\n".join(lines)


async def run_preservation_check(
    *,
    target: EntitySet,
    output_artifact_id: str,
    intent: str,
) -> tuple[dict, PreservationScore | None]:
    """Score how well an output artifact preserved target entities.

    Returns (SSE event payload, PreservationScore | None). The score is
    forwarded to the critic so it doesn't have to re-extract entities.
    Falls back to a `status=failed` payload (and None score) if extraction
    errors out — preservation is advisory in Phase 3.
    """
    try:
        output_entities = await extract_entities(output_artifact_id)
    except Exception as e:
        logger.warning(f"Output entity extraction failed: {e}")
        return {
            "type": EVENT_PRESERVATION,
            "status": STATUS_FAILED,
            "intent": intent,
            "output_artifact_id": output_artifact_id,
            "error": str(e),
        }, None

    score = compute_preservation_score(
        target=target, output=output_entities, intent=intent,
    )
    return {
        "type": EVENT_PRESERVATION,
        "status": STATUS_COMPLETED,
        "intent": intent,
        "output_artifact_id": output_artifact_id,
        "score": score.model_dump(),
    }, score


# ──────────────────────────────────────────────────────────────────────
# Phase 4 — Critic review
# ──────────────────────────────────────────────────────────────────────

async def run_critic_review(
    *,
    output_artifact_id: str,
    user_text: str,
    intent: str,
    style_source_kind: str,
    preservation: PreservationScore | None,
) -> dict:
    """Run the Phase 4 critic review and return the SSE event payload.

    Failures are caught and surfaced as `status=failed` so the rest of the
    response still streams cleanly.
    """
    try:
        result = await run_critic(
            output_artifact_id=output_artifact_id,
            user_text=user_text,
            intent=intent,
            style_source_kind=style_source_kind,
            preservation=preservation,
        )
    except Exception as e:
        logger.warning(f"Critic review failed: {e}")
        return {
            "type": EVENT_CRITIC_RESULT,
            "status": STATUS_FAILED,
            "intent": intent,
            "output_artifact_id": output_artifact_id,
            "error": str(e),
        }
    return {
        "type": EVENT_CRITIC_RESULT,
        "status": STATUS_COMPLETED,
        "intent": intent,
        "output_artifact_id": output_artifact_id,
        "result": result.model_dump(),
    }


# ──────────────────────────────────────────────────────────────────────
# Phase 4.5 — Retry continuation message + pairwise comparison
# ──────────────────────────────────────────────────────────────────────

# Caps on critic input rendered into the retry message. Higher = more
# context for v2 but also more tokens; tune if v2 quality drifts.
_RETRY_MESSAGE_MAX_ISSUES = 8
_RETRY_MESSAGE_MAX_MISSING = 10


def build_retry_message(
    *,
    critic_result: dict,
    preservation_score: PreservationScore | None,
) -> types.Content:
    """Construct the continuation message that drives v2 generation.

    The agent receives this as a "user follow-up" via the same ADK session.
    It contains the critic's verdict, retry_hint, and any preserved-info
    losses so the agent can target its fixes precisely.
    """
    result = critic_result.get("result") or {}
    retry_hint = result.get("retry_hint") or "(なし)"
    issues = result.get("issues") or []

    lines = [
        "━━━ Critic フィードバック ━━━",
        "verdict=retry のため再生成してください。",
        "",
        f"retry_hint: {retry_hint}",
    ]
    if issues:
        lines.append("")
        lines.append("具体的な指摘:")
        for it in issues[:_RETRY_MESSAGE_MAX_ISSUES]:
            slide = it.get("slide")
            shape_idx = it.get("shape_idx")
            kind = it.get("kind", "other")
            msg = it.get("msg", "")
            loc = []
            if slide is not None:
                loc.append(f"slide={slide}")
            if shape_idx is not None:
                loc.append(f"shape={shape_idx}")
            loc_str = f"[{', '.join(loc)}] " if loc else ""
            lines.append(f"  - {loc_str}({kind}) {msg}")

    if preservation_score is not None and not preservation_score.passed:
        lines.append("")
        lines.append(
            f"preservation: matched={preservation_score.matched}/"
            f"{preservation_score.total} (ratio={preservation_score.ratio:.2f}) — 不合格"
        )
        if preservation_score.missing:
            lines.append("失われたエンティティ (必ず復活させてください):")
            for m in preservation_score.missing[:_RETRY_MESSAGE_MAX_MISSING]:
                lines.append(
                    f"  - [{m.type}] {m.value} (元 slide {m.source_slide_idx})"
                )

    lines += ["", "上記を踏まえて、必要なツールで修正版を生成してください。"]
    return types.Content(role="user", parts=[types.Part(text="\n".join(lines))])


async def run_pairwise_compare(
    *,
    v1_artifact_id: str,
    v2_artifact_id: str,
    user_text: str,
    intent: str,
    weighted_v1: float | None,
    weighted_v2: float | None,
) -> tuple[dict, str]:
    """Run pairwise comparison and return (SSE event payload, winner artifact id).

    Failures fall back to picking v1 (the safer choice — keep what we had).
    """
    try:
        result = await compare_pairwise(
            v1_artifact_id=v1_artifact_id,
            v2_artifact_id=v2_artifact_id,
            user_text=user_text,
            intent=intent,
        )
    except Exception as e:
        logger.warning(f"Pairwise compare failed, defaulting to v1: {e}")
        return (
            {
                "type": EVENT_PAIRWISE_COMPARE,
                "status": STATUS_FAILED,
                "intent": intent,
                "v1_artifact_id": v1_artifact_id,
                "v2_artifact_id": v2_artifact_id,
                "winner": "v1",
                "error": str(e),
            },
            v1_artifact_id,
        )

    winner_label = decide_winner(
        pairwise=result,
        weighted_v1=weighted_v1,
        weighted_v2=weighted_v2,
        tie_break_margin=PAIRWISE_TIE_BREAK_MARGIN,
    )
    winner_id = v2_artifact_id if winner_label == "v2" else v1_artifact_id
    return (
        {
            "type": EVENT_PAIRWISE_COMPARE,
            "status": STATUS_COMPLETED,
            "intent": intent,
            "v1_artifact_id": v1_artifact_id,
            "v2_artifact_id": v2_artifact_id,
            "winner": winner_label,
            "reasoning": result.reasoning,
        },
        winner_id,
    )
