"""Entity extraction for the preservation check (Phase 3).

Pulls EntitySet from a PPTX artifact via a single Gemini call (lite tier —
this task doesn't need Pro). Cached by artifact id with the standard
ARTIFACT_TTL.

Intentionally separate from style_extractor.py: the prompts have different
goals (visual style vs. textual fact extraction) and different cost profiles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from google.genai import types as genai_types

from src.agents.preservation_schema import EntitySet
from src.config import settings
from src.constants import ARTIFACT_TTL, ENTITY_EXTRACT_TEXT_RUNS_PER_SHAPE
from src.services.artifact_store import get_artifact
from src.services.genai_client import get_genai_client, with_genai_retry
from src.services.pptx_skill import inspect_pptx

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Cache
# ──────────────────────────────────────────────────────────────────────

@dataclass
class _CachedEntities:
    artifact_id: str
    entities: EntitySet
    created_at: datetime = field(default_factory=datetime.now)


_cache: dict[str, _CachedEntities] = {}


def _cleanup_expired() -> None:
    now = datetime.now()
    expired = [aid for aid, e in _cache.items() if now - e.created_at > ARTIFACT_TTL]
    for aid in expired:
        del _cache[aid]


def get_cached_entities(artifact_id: str) -> EntitySet | None:
    _cleanup_expired()
    entry = _cache.get(artifact_id)
    return entry.entities if entry else None


def put_cached_entities(artifact_id: str, entities: EntitySet) -> None:
    _cache[artifact_id] = _CachedEntities(artifact_id=artifact_id, entities=entities)
    logger.info(
        f"Cached {len(entities.entities)} entities for artifact {artifact_id}"
    )


def invalidate_entities(artifact_id: str) -> None:
    if artifact_id in _cache:
        del _cache[artifact_id]
        logger.info(f"Invalidated entity cache for artifact {artifact_id}")


# ──────────────────────────────────────────────────────────────────────
# Extraction
# ──────────────────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """\
あなたは PPTX のスライドからユーザーの「事実情報」を抜き出す抽出器です。
以下の各スライドのテキストから、再構成で失うと困る情報をエンティティとして
列挙してください。

## 抽出対象

- person: 個人名 (例: "山田太郎", "John Smith")
- organization: 企業・団体・部署 (例: "Acme Inc", "営業部")
- location: 地名・施設 (例: "東京", "渋谷オフィス")
- number: 統計値・割合・倍率 (例: "42%", "1.5x", "100万人")
- date: 日付・期間 (例: "2026-Q2", "2024年4月", "来月")
- money: 金額 (例: "¥10,000", "$5M", "1億円")
- product: 製品・サービス名
- key_term: 専門用語・固有概念 (例: "MAU", "ARR", "OKR")
- url: URL
- email: メールアドレス

## 抽出ルール

1. **value は正規化形** — 全角/半角を半角に、不要な空白を削除。
   例: "４２％" → "42%", "２０２４年" → "2024年"
2. value と元テキストが大きく異なる場合のみ raw に元テキストを残す。
3. **同一エンティティが複数スライドに出る場合は各スライドで1個ずつ列挙**
   (slide_idx が違えば別エンティティ扱い)。
4. **接続詞/助詞/動詞** (例: "が", "を", "した") は抽出しない。
5. 抽出に確信が持てないものはスキップ — 不要な誤検知より漏れを許容。
6. 各スライドあたり 0〜30 個程度を目安。
"""


def _build_text_summary(info: dict[str, Any]) -> str:
    """Render slide-by-slide text content for the LLM (no PNGs — text only)."""
    lines: list[str] = []
    for slide in info.get("slides", []):
        si = slide.get("slide_idx", 0)
        lines.append(f"--- スライド {si} ---")
        for shape in slide.get("shapes", []):
            for tr in shape.get("text_runs", [])[:ENTITY_EXTRACT_TEXT_RUNS_PER_SHAPE]:
                txt = tr.get("text", "")
                if txt and txt.strip():
                    lines.append(f"  {txt}")
            tbl = shape.get("table")
            if tbl:
                for row in tbl.get("cells", []):
                    for cell in row:
                        ct = cell.get("text", "")
                        if ct and ct.strip():
                            lines.append(f"  [cell] {ct}")
    return "\n".join(lines)


async def extract_entities(
    artifact_id: str,
    *,
    use_cache: bool = True,
) -> EntitySet:
    """Extract an EntitySet from a stored PPTX artifact.

    Caches by artifact id. Raises ValueError when the artifact isn't stored,
    RuntimeError when the LLM call fails or returns malformed output.
    """
    if use_cache:
        cached = get_cached_entities(artifact_id)
        if cached is not None:
            logger.info(f"Entity cache hit for artifact {artifact_id}")
            return cached

    artifact = get_artifact(artifact_id)
    if artifact is None:
        raise ValueError(f"Artifact not found: {artifact_id}")

    info = await inspect_pptx(artifact.data, with_png=False)
    text_summary = _build_text_summary(info)
    if not text_summary.strip():
        # 空PPTX: 何も抽出できない。空セットを返してキャッシュ。
        empty = EntitySet(entities=[])
        put_cached_entities(artifact_id, empty)
        return empty

    parts = [
        genai_types.Part(text=_EXTRACTION_PROMPT),
        genai_types.Part(text="スライド本文:\n" + text_summary),
    ]
    model_id = settings.resolve_model(settings.agent_preservation_model)
    client = get_genai_client()
    logger.info(
        f"Extracting entities for artifact {artifact_id} with model={model_id} "
        f"(text length={len(text_summary)})"
    )

    try:
        response = await with_genai_retry(
            lambda: client.aio.models.generate_content(
                model=model_id,
                contents=genai_types.Content(role="user", parts=parts),
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EntitySet,
                ),
            ),
            label="entity_extract",
        )
    except Exception as e:
        raise RuntimeError(f"Entity extraction LLM call failed: {e}") from e

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, EntitySet):
        result = parsed
    else:
        raw_text = getattr(response, "text", "") or ""
        if not raw_text:
            raise RuntimeError(
                "Entity extraction returned no parsed object and no text"
            )
        try:
            result = EntitySet.model_validate_json(raw_text)
        except Exception as e:
            raise RuntimeError(f"Entity extraction returned invalid JSON: {e}") from e

    put_cached_entities(artifact_id, result)
    return result
