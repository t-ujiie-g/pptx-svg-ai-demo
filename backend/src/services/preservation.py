"""Preservation scoring (Phase 3).

Compares the entity set extracted from the *target* PPTX against the entity
set extracted from the agent's output, returning a `PreservationScore`.

Matching strategy (deterministic, fast):
  1. Normalize each entity value (full-width → half-width, strip whitespace,
     casefold for ASCII).
  2. A target entity is "preserved" when an output entity exists with the same
     `(type, normalized_value)`. Slide index is *not* part of the key —
     restructure may move things around.
  3. Numeric/money values use loose normalization too (¥ / 円 / , / .) so
     "1,000円" and "¥1000" match.

Threshold and what counts as "passed" come from constants by intent.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from src.agents.preservation_schema import (
    Entity,
    EntitySet,
    MissingEntity,
    PreservationScore,
)
from src.constants import (
    PRESERVATION_THRESHOLD_POLISH,
    PRESERVATION_THRESHOLD_RESTRUCTURE,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Threshold lookup
# ──────────────────────────────────────────────────────────────────────

# Only `polish` and `restructure` are checked. `tweak` keeps target structure
# intact (no entity loss expected) and `from-scratch` has no target to compare.
_THRESHOLDS: dict[str, float] = {
    "polish": PRESERVATION_THRESHOLD_POLISH,
    "restructure": PRESERVATION_THRESHOLD_RESTRUCTURE,
}


def threshold_for_intent(intent: str) -> float | None:
    """Threshold for an intent, or None if preservation should be skipped."""
    return _THRESHOLDS.get(intent)


# ──────────────────────────────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────────────────────────────

# Strip currency markers and grouping/decimal punctuation for number/money so
# "¥1,000" "1000円" "1,000" all collapse to the same key. We do not strip
# the actual digits, just decoration.
_NUMERIC_TYPES = frozenset({"number", "money"})
_NUMERIC_NOISE_RE = re.compile(r"[¥$€£,\s円]+")


def _normalize_value(entity_type: str, value: str) -> str:
    """Normalize an entity value for equality comparison.

    `unicodedata.normalize('NFKC', ...)` handles full→half width plus
    visually-equivalent compat forms (e.g. ㈱ → (株)). Casefold makes ASCII
    case-insensitive without breaking Japanese.
    """
    s = unicodedata.normalize("NFKC", value).strip().casefold()
    if entity_type in _NUMERIC_TYPES:
        s = _NUMERIC_NOISE_RE.sub("", s)
    return s


def _entity_key(entity: Entity) -> tuple[str, str]:
    return entity.type, _normalize_value(entity.type, entity.value)


# ──────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────

def compute_preservation_score(
    *,
    target: EntitySet,
    output: EntitySet,
    intent: str,
) -> PreservationScore:
    """Score how well `output` preserves entities from `target`.

    Returns a PreservationScore with `passed=True` when ratio >= threshold.
    Caller is responsible for skipping the call when intent has no threshold.
    """
    threshold = _THRESHOLDS.get(intent)
    if threshold is None:
        # Should not reach here when caller follows `threshold_for_intent`.
        # Default to a permissive threshold so the result is usable.
        threshold = 0.0

    output_keys = {_entity_key(e) for e in output.entities}

    matched = 0
    missing: list[MissingEntity] = []
    seen_target_keys: set[tuple[str, str]] = set()
    for ent in target.entities:
        key = _entity_key(ent)
        # Same target entity in multiple slides counts once at the set level —
        # otherwise a single missing fact would tank the ratio.
        if key in seen_target_keys:
            continue
        seen_target_keys.add(key)
        if key in output_keys:
            matched += 1
        else:
            missing.append(MissingEntity(
                type=ent.type,
                value=ent.value,
                source_slide_idx=ent.slide_idx,
            ))

    total = len(seen_target_keys)
    ratio = (matched / total) if total > 0 else 1.0
    passed = ratio >= threshold

    score = PreservationScore(
        threshold=threshold,
        matched=matched,
        total=total,
        ratio=ratio,
        missing=missing,
        passed=passed,
    )
    logger.info(f"Preservation score (intent={intent}): {score.summary}")
    return score
