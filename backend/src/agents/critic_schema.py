"""CriticResult — independent quality review of the agent's output (Phase 4).

After the PPTX agent finishes, a separate Gemini call evaluates the result
along five axes. Independence from the generator avoids the "agents grade
their own homework" failure mode.

Phase 4 (this file): the result is reported via SSE and displayed; no retry.
Phase 4.5 will use `verdict == "retry"` + `retry_hint` to drive a single
re-prompt + pairwise comparison + rollback.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CriticVerdict = Literal["accept", "retry", "reject"]

# Issue taxonomy. Coarse on purpose — finer-grained tags drift between
# critic calls without improving fix quality.
CriticIssueKind = Literal[
    "overflow",         # text spills outside its shape / off-slide
    "low_contrast",     # text-bg or icon-bg contrast too low
    "layout_break",     # misaligned / overlapping shapes
    "missing_info",     # key entity from target was lost (links to preservation)
    "off_intent",       # didn't follow the user's explicit ask
    "design_weak",      # bland / inconsistent / ugly
    "inconsistent",     # styling differs across slides
    "ai_telltale",      # accent lines under titles, generic templates, etc.
    "other",
]


class CriticIssue(BaseModel):
    """One concrete problem the critic spotted."""

    slide: int | None = Field(
        default=None,
        description="該当スライドindex (0-based)。デッキ全体の問題なら null",
    )
    shape_idx: int | None = Field(
        default=None,
        description="該当shape index (0-based)。スライド全体の問題なら null",
    )
    kind: CriticIssueKind
    msg: str = Field(description="日本語の短い説明 (1行)")


class CriticScores(BaseModel):
    """Five axes each in [0,1]. The weighted total is computed by the service,
    not the LLM, so weights stay deterministic per intent."""

    intent_fit: float = Field(ge=0.0, le=1.0)
    design: float = Field(ge=0.0, le=1.0)
    consistency: float = Field(ge=0.0, le=1.0)
    info_density: float = Field(ge=0.0, le=1.0)
    preservation: float = Field(ge=0.0, le=1.0)


class CriticResult(BaseModel):
    """Top-level critic output. Used as Gemini's response_schema."""

    scores: CriticScores
    issues: list[CriticIssue] = Field(default_factory=list)
    verdict: CriticVerdict = Field(
        description="LLMの暫定判定。サービスが weighted threshold で再計算する"
    )
    retry_hint: str = Field(
        default="",
        description=(
            "verdict='retry' のとき、再生成エージェントに渡す具体的な改善指示。"
            "1〜3文の日本語で。Phase 4.5で使用。"
        ),
    )
    # 非LLMフィールド (サービス側で埋める。LLMのresponse_schemaでは無視されるが
    # Pydanticが許容してくれる方が後段が楽)
    weighted: float | None = Field(
        default=None,
        description="サービスが intent別重みで計算した加重平均",
    )


# ──────────────────────────────────────────────────────────────────────
# Pairwise comparison (Phase 4.5)
# ──────────────────────────────────────────────────────────────────────

PairwiseWinner = Literal["v1", "v2", "tie"]


class PairwiseResult(BaseModel):
    """Independent ペアワイズ比較 of v1 vs v2.

    A separate LLM judges which version is better given the user's intent.
    More reliable than comparing absolute scores, which drift between calls.
    """

    winner: PairwiseWinner
    reasoning: str = Field(description="勝者を選んだ短い根拠 (日本語、1〜3文)")
