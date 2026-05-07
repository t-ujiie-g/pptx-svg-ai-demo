"""Critic — independent post-generation review (Phase 4).

After the PPTX agent finishes, this service runs an independent Gemini call
to score the output along 5 axes (intent_fit, design, consistency,
info_density, preservation). The weighted total + an LLM-suggested verdict
combine into the final `accept | retry | reject` decision.

Independence note: this uses a separate genai client + prompt from the agent
itself. Don't fold this into pptx_agent — the whole point is that the critic
shouldn't share thinking-context with the generator.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from google.genai import types as genai_types

from src.agents.critic_schema import (
    CriticIssue,
    CriticResult,
    CriticScores,
    PairwiseResult,
)
from src.agents.preservation_schema import PreservationScore
from src.config import settings
from src.constants import (
    CRITIC_ACCEPT_WEIGHTED,
    CRITIC_AXES,
    CRITIC_ISSUES_MAX,
    CRITIC_REJECT_WEIGHTED,
    CRITIC_WEIGHTS_BY_INTENT,
)
from src.services.artifact_store import get_artifact
from src.services.genai_client import get_genai_client, with_genai_retry
from src.services.pptx_skill import inspect_pptx

logger = logging.getLogger(__name__)


_PROMPT = """\
あなたはプレゼンテーション (PPTX) を独立に評価する Critic です。
生成エージェントとは別の視点で、出力スライドを採点してください。

## 入力
- ユーザーの元リクエスト
- mode_spec (intent / style_source)
- 生成された PPTX (各スライドの PNG + 構造情報)
- 必要に応じて preservation score (情報保全率)

## 評価軸 (各 0.0 - 1.0)

1. **intent_fit**: ユーザーの依頼にどれだけ応えているか。
   - 例: 「タイトル変えて」と言われて変わっていれば 1.0、見当違いなら 0.0
2. **design**: 視覚デザインの完成度。
   - 配色のバランス、余白、フォント選定、装飾の意図性。
   - **タイトル下のアクセント線を「使っている」ら -0.2** (AI生成スライドの典型悪パターン)
   - 全スライド同じレイアウトなら -0.1 (リズム感がない)
3. **consistency**: スライド間の統一感。
   - 配色・フォントサイズ・余白が一貫しているか。
4. **info_density**: 1スライドあたりの情報量の適切さ。
   - 詰め込みすぎ (text overflow) も、スカスカも減点。
5. **preservation**: 元の情報がどれだけ残っているか。
   - preservation score が与えられている場合はそれをそのまま採用。
   - intent=from-scratch (target無し) なら 1.0 で固定。

## 問題 (issues) の挙げ方

具体的な問題を最大 {issues_max} 件まで列挙してください。
- slide / shape_idx は分かれば指定。デッキ全体の問題なら null。
- kind は次から選択: overflow / low_contrast / layout_break / missing_info /
  off_intent / design_weak / inconsistent / ai_telltale / other
- msg は1行の日本語で具体的に (例: "本文がスライド下端からはみ出している")

## verdict

最後に accept / retry / reject のいずれかを判定してください。
- **accept**: 概ね合格。修正の必要なし。
- **retry**: 修正可能な問題があり、もう一度生成し直す価値がある。
  → retry_hint に「次の生成エージェントへの具体的な改善指示」を1〜3文で記載。
- **reject**: 致命的に壊れていて、修正より作り直しを推奨。

retry_hint の例:
- "本文shapeのcyを増やし、フォントサイズを-2pt して overflow を解消すること。"
- "全スライドで同じ余白 (0.5インチ) と同じ accent 色 (#F96167) を使うこと。"
"""


def _build_inputs(
    *,
    user_text: str,
    intent: str,
    style_source_kind: str,
    info: dict[str, Any],
    preservation: PreservationScore | None,
) -> tuple[str, list[bytes]]:
    """Render text summary + collect slide PNGs for the critic call."""
    lines = [
        "## ユーザーの元リクエスト",
        user_text or "(空)",
        "",
        f"## mode_spec: intent={intent}, style_source.kind={style_source_kind}",
    ]
    if preservation is not None:
        lines += [
            "",
            "## preservation score (Phase 3 結果)",
            f"matched={preservation.matched}/{preservation.total} "
            f"ratio={preservation.ratio:.2f} (threshold={preservation.threshold:.2f}) "
            f"{'PASS' if preservation.passed else 'FAIL'}",
        ]
        if preservation.missing:
            lines.append("欠損エンティティ:")
            for m in preservation.missing[:10]:
                lines.append(f"  - [{m.type}] {m.value} (slide {m.source_slide_idx})")

    lines += [
        "",
        f"## 出力スライド ({info.get('slide_count', 0)} 枚)",
        f"スライドサイズ: {info.get('slide_width_emu', 0)} x "
        f"{info.get('slide_height_emu', 0)} EMU",
        "",
    ]
    pngs: list[bytes] = []
    for slide in info.get("slides", []):
        si = slide.get("slide_idx", 0)
        lines.append(f"--- スライド {si} ---")
        for shape in slide.get("shapes", []):
            idx = shape.get("idx", "?")
            stype = shape.get("shape_type", "?")
            x, y = shape.get("x", 0), shape.get("y", 0)
            cx, cy = shape.get("cx", 0), shape.get("cy", 0)
            fill = shape.get("fill_hex", "")
            line = f"  shape[{idx}] type={stype} pos=({x},{y}) size=({cx},{cy})"
            if fill:
                line += f" fill=#{fill}"
            lines.append(line)
            for tr in shape.get("text_runs", [])[:4]:
                txt = tr.get("text", "")
                if txt and txt.strip():
                    lines.append(f"    text: {txt!r}")
        png_b64 = slide.get("png_base64")
        if png_b64:
            try:
                pngs.append(base64.b64decode(png_b64))
            except Exception as e:
                logger.warning(f"Failed to decode PNG for slide {si}: {e}")

    return "\n".join(lines), pngs


def _compute_weighted(scores: CriticScores, intent: str) -> float:
    """Compute the intent-weighted total score in [0,1]."""
    weights = CRITIC_WEIGHTS_BY_INTENT.get(intent, CRITIC_WEIGHTS_BY_INTENT["polish"])
    score_dump = scores.model_dump()
    return sum(score_dump[axis] * weights.get(axis, 0.0) for axis in CRITIC_AXES)


def _final_verdict(
    weighted: float,
    llm_verdict: str,
    has_issues: bool,
) -> str:
    """Reconcile the LLM-suggested verdict with the weighted threshold.

    Trust the LLM when it says "reject" — it's seeing visual issues we may not
    catch numerically. Otherwise let the weighted score decide so a hallucinated
    "accept" with low scores doesn't slip through.
    """
    if llm_verdict == "reject":
        return "reject"
    if weighted >= CRITIC_ACCEPT_WEIGHTED and not has_issues:
        return "accept"
    if weighted < CRITIC_REJECT_WEIGHTED:
        return "reject"
    return "retry"


async def run_critic(
    *,
    output_artifact_id: str,
    user_text: str,
    intent: str,
    style_source_kind: str,
    preservation: PreservationScore | None = None,
) -> CriticResult:
    """Score the output PPTX. Raises ValueError if the artifact is missing."""
    artifact = get_artifact(output_artifact_id)
    if artifact is None:
        raise ValueError(f"Output artifact not found: {output_artifact_id}")

    info = await inspect_pptx(artifact.data, with_png=True)
    text_summary, pngs = _build_inputs(
        user_text=user_text,
        intent=intent,
        style_source_kind=style_source_kind,
        info=info,
        preservation=preservation,
    )

    parts: list[genai_types.Part] = [
        genai_types.Part(text=_PROMPT.format(issues_max=CRITIC_ISSUES_MAX)),
        genai_types.Part(text=text_summary),
    ]
    for i, png in enumerate(pngs):
        parts.append(genai_types.Part(text=f"[スライド {i} の見た目]"))
        parts.append(genai_types.Part.from_bytes(data=png, mime_type="image/png"))

    model_id = settings.resolve_model(settings.agent_critic_model)
    client = get_genai_client()
    logger.info(
        f"Running critic on artifact {output_artifact_id} with model={model_id} "
        f"(intent={intent}, slides={len(pngs)})"
    )

    try:
        response = await with_genai_retry(
            lambda: client.aio.models.generate_content(
                model=model_id,
                contents=genai_types.Content(role="user", parts=parts),
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CriticResult,
                ),
            ),
            label="critic",
        )
    except Exception as e:
        raise RuntimeError(f"Critic LLM call failed: {e}") from e

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, CriticResult):
        result = parsed
    else:
        raw_text = getattr(response, "text", "") or ""
        if not raw_text:
            raise RuntimeError("Critic returned no parsed object and no text")
        try:
            result = CriticResult.model_validate_json(raw_text)
        except Exception as e:
            raise RuntimeError(f"Critic returned invalid JSON: {e}") from e

    # サービス側で重み付け & verdict 補正
    weighted = _compute_weighted(result.scores, intent)
    issues_capped = result.issues[:CRITIC_ISSUES_MAX]
    final = _final_verdict(weighted, result.verdict, has_issues=bool(issues_capped))

    out = CriticResult(
        scores=result.scores,
        issues=issues_capped,
        verdict=final,  # type: ignore[arg-type]
        retry_hint=result.retry_hint,
        weighted=weighted,
    )
    logger.info(
        f"Critic verdict={final} weighted={weighted:.2f} issues={len(issues_capped)} "
        f"(intent={intent})"
    )
    return out


def coerce_preservation_from_event(score_dict: dict | None) -> PreservationScore | None:
    """Helper: convert a preservation SSE payload's `score` dict back to a model.

    Lets chat.py reuse the Phase 3 result for the critic call without
    re-running the comparison. Returns None when dict is missing/invalid.
    """
    if not isinstance(score_dict, dict):
        return None
    try:
        return PreservationScore(**score_dict)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────
# Pairwise comparison (Phase 4.5)
# ──────────────────────────────────────────────────────────────────────

_PAIRWISE_PROMPT = """\
あなたは2つのプレゼンテーション v1 と v2 をペアワイズに比較する独立評価者です。
ユーザーの依頼に対して **どちらの方が良いか** だけを判断してください。

## 評価基準 (intent={intent} 用に重み付けして判断)

- intent_fit: ユーザーの依頼にどれだけ応えているか
- design: 視覚デザインの完成度 (アクセント線・コントラスト・余白)
- consistency: スライド間の統一感
- preservation: 元の情報の保持 (intent=polish/restructure 時のみ重要)

## 判断手順 (必ず守る)

1. **同じスライド番号同士で対比** してから総合判断する。
   - スライド0 v1 と スライド0 v2 を比較
   - スライド1 v1 と スライド1 v2 を比較 ... を全スライド分行う。
2. v2 は v1 への修正版 (Critic から retry指示を受けて再生成) です。基本的には
   修正で良くなっている前提で、明らかに悪化していなければ v2 を優先。
   - **「変わっていないように見えた」「微差」の場合も v2 を選ぶ** (修正の意図を尊重)。
   - v2 が明確に v1 より悪化している (テキスト欠落・大きな崩れ) 場合のみ v1 を選ぶ。
3. 一方の中身が読み取れない (フォント未対応で豆腐文字など) ときは、**その評価軸は
   無視** し、レイアウトのみで判定。両方とも豆腐ならレイアウトと余白で比較。
4. reasoning は1〜3文の日本語で。判断したスライド番号も触れる。

## 判定の優先順 (上から順に適用)

- v2 にだけ深刻な破綻 (内容ロス / overflow / 完全に重なる) → "v1"
- v1 にだけ深刻な破綻 → "v2"
- v2 が明らかに改善している (Critic 指摘箇所が直っている) → "v2"
- 体感的に v2 = v1 → "v2" (修正意図を尊重)
- 比較できないほど両方崩れている → "tie"

入力:
1. ユーザーの元リクエスト
2. v1 の各スライド PNG
3. v2 の各スライド PNG
"""


async def compare_pairwise(
    *,
    v1_artifact_id: str,
    v2_artifact_id: str,
    user_text: str,
    intent: str,
) -> PairwiseResult:
    """Ask Gemini which of two PPTX artifacts better matches the user's ask.

    Raises ValueError when either artifact is missing.
    """
    v1 = get_artifact(v1_artifact_id)
    v2 = get_artifact(v2_artifact_id)
    if v1 is None:
        raise ValueError(f"v1 artifact not found: {v1_artifact_id}")
    if v2 is None:
        raise ValueError(f"v2 artifact not found: {v2_artifact_id}")

    v1_info = await inspect_pptx(v1.data, with_png=True)
    v2_info = await inspect_pptx(v2.data, with_png=True)

    parts: list[genai_types.Part] = [
        genai_types.Part(text=_PAIRWISE_PROMPT.format(intent=intent)),
        genai_types.Part(text=f"## ユーザーの元リクエスト\n{user_text or '(空)'}"),
        genai_types.Part(text=f"## v1 ({v1_info.get('slide_count', 0)} 枚)"),
    ]
    for i, slide in enumerate(v1_info.get("slides", [])):
        png_b64 = slide.get("png_base64")
        if png_b64:
            parts.append(genai_types.Part(text=f"[v1 スライド {i}]"))
            parts.append(genai_types.Part.from_bytes(
                data=base64.b64decode(png_b64), mime_type="image/png",
            ))
    parts.append(genai_types.Part(
        text=f"## v2 ({v2_info.get('slide_count', 0)} 枚)",
    ))
    for i, slide in enumerate(v2_info.get("slides", [])):
        png_b64 = slide.get("png_base64")
        if png_b64:
            parts.append(genai_types.Part(text=f"[v2 スライド {i}]"))
            parts.append(genai_types.Part.from_bytes(
                data=base64.b64decode(png_b64), mime_type="image/png",
            ))

    model_id = settings.resolve_model(settings.agent_critic_model)
    client = get_genai_client()
    logger.info(
        f"Pairwise compare v1={v1_artifact_id} v2={v2_artifact_id} "
        f"with model={model_id} (intent={intent})"
    )

    try:
        response = await with_genai_retry(
            lambda: client.aio.models.generate_content(
                model=model_id,
                contents=genai_types.Content(role="user", parts=parts),
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PairwiseResult,
                ),
            ),
            label="pairwise",
        )
    except Exception as e:
        raise RuntimeError(f"Pairwise compare LLM call failed: {e}") from e

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, PairwiseResult):
        result = parsed
    else:
        raw_text = getattr(response, "text", "") or ""
        if not raw_text:
            raise RuntimeError("Pairwise returned no parsed object and no text")
        try:
            result = PairwiseResult.model_validate_json(raw_text)
        except Exception as e:
            raise RuntimeError(f"Pairwise returned invalid JSON: {e}") from e

    logger.info(f"Pairwise winner={result.winner}: {result.reasoning[:120]}")
    return result


def decide_winner(
    *,
    pairwise: PairwiseResult,
    weighted_v1: float | None,
    weighted_v2: float | None,
    tie_break_margin: float,
) -> str:
    """Reconcile the LLM pairwise call with the weighted scores.

    Phase 4.5 lessons learned: when in doubt, prefer v2 (the retry was a
    deliberate improvement attempt — keeping v1 by default ignores the user's
    feedback signal). v1 only wins when it's measurably better.

    Returns "v1" or "v2".
    """
    if pairwise.winner != "tie":
        return pairwise.winner
    if weighted_v1 is None or weighted_v2 is None:
        # スコア欠損時も改善側を尊重して v2 を採用 (失敗回避は preservation
        # と critic で既に拾えている)
        return "v2"
    # v1 が明確に勝っている時だけ v1 を採用。それ以外は v2 (修正意図を尊重)。
    if weighted_v1 - weighted_v2 >= tie_break_margin:
        return "v1"
    return "v2"


# Re-export the top-level submodule helpers for chat.py
__all__ = [
    "run_critic",
    "compare_pairwise",
    "decide_winner",
    "coerce_preservation_from_event",
    "CriticIssue",
    "CriticResult",
    "CriticScores",
    "PairwiseResult",
]
