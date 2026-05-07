"""In-memory cache: artifact_id -> StyleSpec.

Style extraction is non-trivial (one Gemini call with N PNG images), so we
cache the result keyed by source artifact id. Entries inherit ARTIFACT_TTL —
when an artifact expires, its cached style spec is dropped on the next access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from src.agents.style_schema import StyleSpec
from src.constants import ARTIFACT_TTL

logger = logging.getLogger(__name__)


@dataclass
class CachedStyle:
    artifact_id: str
    spec: StyleSpec
    created_at: datetime = field(default_factory=datetime.now)


_cache: dict[str, CachedStyle] = {}


def get_cached_style(artifact_id: str) -> StyleSpec | None:
    _cleanup_expired()
    entry = _cache.get(artifact_id)
    if entry is None:
        return None
    return entry.spec


def put_cached_style(artifact_id: str, spec: StyleSpec) -> None:
    _cache[artifact_id] = CachedStyle(artifact_id=artifact_id, spec=spec)
    logger.info(f"Cached style for artifact {artifact_id}")


def invalidate_style(artifact_id: str) -> None:
    """Drop the cached entry. Call on artifact update so we re-extract."""
    if artifact_id in _cache:
        del _cache[artifact_id]
        logger.info(f"Invalidated style cache for artifact {artifact_id}")


def _cleanup_expired() -> None:
    now = datetime.now()
    expired = [aid for aid, e in _cache.items() if now - e.created_at > ARTIFACT_TTL]
    for aid in expired:
        del _cache[aid]
