"""Rule-based mode inference.

Phase 1 keeps inference fully deterministic — no LLM call in the request path.
The user can always override the result in the UI.

Inference policy:
  - target無し + style_ref無し  → from-scratch + preset:best-practice
  - target無し + style_ref有り  → from-scratch + from-ref
  - target有り + style_ref無し  → 短い指示=tweak / 長い・"作り直して"系=restructure
                                   それ以外は polish。style_source は from-target
  - target有り + style_ref有り  → polish + from-ref

キーワードは控えめに。当たらなければデフォルト寄りに倒す（保守的）。

⚠️ 同一ロジックがフロントの `frontend/src/types/modeSpec.ts` (inferModeSpec)
にも実装されています。ルール変更時は両方更新してください（送信前のUIプレビューと
バックエンド最終確定の挙動が一致しないとモードが揺れます）。
"""

from __future__ import annotations

import re

from src.agents.mode.schema import Intent, ModeSpec, StyleSource

# 「ガラッと」「リデザイン」「作り直し」は明確な restructure シグナル。
_RESTRUCTURE_PATTERNS = [
    r"作り直",
    r"リデザイン",
    r"ガラッと",
    r"ゼロから",
    r"全面的に",
    r"一新",
    r"刷新",
]
# 「整えて」「綺麗に」「体裁」は polish シグナル。
_POLISH_PATTERNS = [
    r"整えて",
    r"きれい",
    r"綺麗",
    r"体裁",
    r"見やすく",
    r"清書",
    r"清書して",
    r"レイアウトを",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def _infer_intent_with_target(text: str) -> Intent:
    """target が存在する前提での intent 推定。"""
    if _matches_any(text, _RESTRUCTURE_PATTERNS):
        return "restructure"
    if _matches_any(text, _POLISH_PATTERNS):
        return "polish"
    # 残りは tweak。文字数だけで restructure に倒すと誤爆するため保守的に倒す。
    return "tweak"


def infer_mode_spec(
    *,
    text: str,
    target_artifact_id: str | None,
    style_ref_artifact_id: str | None,
) -> ModeSpec:
    """Deterministic mode spec inference. Always returns a valid ModeSpec.

    The result is marked auto_inferred=True so the UI can display it as a
    "tentative" choice and let the user override.
    """
    has_target = bool(target_artifact_id)
    has_ref = bool(style_ref_artifact_id)
    text = text or ""

    if not has_target:
        intent: Intent = "from-scratch"
        if has_ref:
            style = StyleSource(kind="from-ref")
        else:
            style = StyleSource(kind="preset", preset="best-practice")
    else:
        intent = _infer_intent_with_target(text)
        if has_ref:
            style = StyleSource(kind="from-ref")
        else:
            style = StyleSource(kind="from-target")

    return ModeSpec(
        intent=intent,
        style_source=style,
        auto_inferred=True,
        user_overridden=False,
    )
