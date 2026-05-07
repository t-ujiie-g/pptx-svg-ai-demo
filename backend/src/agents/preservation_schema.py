"""EntitySet / PreservationScore — information preservation (Phase 3).

When `intent` is `polish` or `restructure`, the agent rewrites/reformats slides
that already contain user data. Reorganization can drop facts silently — the
critic-style content review can't always catch this. To guard against that we:

  1. Extract entities (numbers, dates, names, key terms) from the *target*
     before generation.
  2. After generation, extract from the result and compute the proportion of
     target entities that survived.
  3. Below an intent-specific threshold the request is flagged for follow-up
     (Phase 3.5: re-prompt with the missing list; Phase 4: critic loop).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Coarse entity taxonomy. Kept small on purpose — the LLM finds these reliably
# in Japanese text; finer-grained types add cost without improving the scoring
# signal.
EntityType = Literal[
    "person",        # 個人名 (山田太郎, John Doe, ...)
    "organization",  # 会社・団体・部署 (Acme Inc, 営業部, ...)
    "location",      # 地名・施設 (東京, Tokyo Station, ...)
    "number",        # 統計値・割合 (42%, 1.5x, 100万円, ...)
    "date",          # 日付・期間 (2026-Q2, 来月, 2024年4月, ...)
    "money",         # 金額 (¥10,000, $5M)。numberと別管理して比較精度を上げる
    "product",       # 製品・サービス名
    "key_term",      # 専門用語・固有概念 (MAU, ARR, OKR, ...)
    "url",
    "email",
    "other",
]


class Entity(BaseModel):
    type: EntityType
    value: str = Field(description="正規化されたエンティティ値（比較に使う）")
    raw: str | None = Field(
        default=None,
        description="抽出元の生テキスト（valueと異なる場合のみ）",
    )
    slide_idx: int = Field(description="抽出元スライドindex (0-based)")


class EntitySet(BaseModel):
    """All entities extracted from one PPTX artifact."""

    version: int = 1
    entities: list[Entity] = Field(default_factory=list)


class MissingEntity(BaseModel):
    type: EntityType
    value: str
    source_slide_idx: int


class PreservationScore(BaseModel):
    """Result of comparing target entities to output entities."""

    threshold: float = Field(ge=0.0, le=1.0)
    matched: int = Field(ge=0)
    total: int = Field(ge=0)
    ratio: float = Field(ge=0.0, le=1.0)
    missing: list[MissingEntity] = Field(default_factory=list)
    passed: bool

    @property
    def summary(self) -> str:
        return (
            f"matched={self.matched}/{self.total} "
            f"ratio={self.ratio:.2f} (threshold={self.threshold:.2f}) "
            f"{'PASS' if self.passed else 'FAIL'}"
        )
