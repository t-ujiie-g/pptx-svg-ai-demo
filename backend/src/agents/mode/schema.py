"""ModeSpec — 3-slot model that drives PPTX generation behavior.

Slots:
  1. Input    : target (artifact_id?) + style_ref (artifact_id?)
  2. Intent   : how much to change the target (tweak/polish/restructure/from-scratch)
  3. Style    : where the visual style comes from (target / ref / preset / mix)

Validation rules (enforced here):
  - intent ∈ {tweak, polish}        ⇒ target_artifact_id is required
  - style_source.kind == "from-ref" ⇒ style_ref_artifact_id is required
  - style_source.kind in {preset, mix} ⇒ preset is required
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)

Intent = Literal["tweak", "polish", "restructure", "from-scratch"]
StyleSourceKind = Literal["from-target", "from-ref", "preset", "mix"]
StylePreset = Literal["best-practice", "bold", "dense", "minimal"]


class StyleSource(BaseModel):
    kind: StyleSourceKind
    preset: StylePreset | None = None
    # When kind == "mix", how much weight to give style_ref (0..1).
    # 1.0 = mostly ref, 0.0 = mostly preset.
    ref_weight: float = 1.0

    @field_validator("ref_weight")
    @classmethod
    def _ref_weight_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("ref_weight must be in [0, 1]")
        return v

    @model_validator(mode="after")
    def _preset_required(self) -> StyleSource:
        if self.kind in {"preset", "mix"} and self.preset is None:
            raise ValueError(
                f"style_source.preset is required when kind={self.kind!r}"
            )
        return self


class ModeSpec(BaseModel):
    intent: Intent
    style_source: StyleSource
    # auto_inferred is True when the backend filled in defaults; False when the
    # user explicitly chose. user_overridden flips True after the user changes
    # an auto-inferred value in the UI.
    auto_inferred: bool = False
    user_overridden: bool = False

    def to_instruction_block(
        self,
        *,
        target_artifact_id: str | None,
        style_ref_artifact_id: str | None,
    ) -> str:
        """Render a deterministic Japanese instruction block for the agent.

        Used by root_agent / pptx_agent to drive routing without re-parsing JSON
        in the model. Keep wording stable so the agent learns one shape.
        """
        lines = [
            "━━━ モード仕様 (mode_spec) ━━━",
            f"intent: {self.intent}",
            f"style_source.kind: {self.style_source.kind}",
        ]
        if self.style_source.preset:
            lines.append(f"style_source.preset: {self.style_source.preset}")
        if self.style_source.kind == "mix":
            lines.append(f"style_source.ref_weight: {self.style_source.ref_weight}")
        lines.append(f"target_artifact_id: {target_artifact_id or '(なし)'}")
        lines.append(f"style_ref_artifact_id: {style_ref_artifact_id or '(なし)'}")
        lines.append("")
        lines.append("ルーティング:")
        if self.intent in ("tweak", "polish"):
            lines.append("  → 既存PPTX編集パス (edit_pptx.py) を使用")
        else:
            lines.append("  → 新規生成パス (generate_pptx.py) を使用")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def validate_against_inputs(
        self,
        *,
        target_artifact_id: str | None,
        style_ref_artifact_id: str | None,
    ) -> None:
        """Cross-check spec against actual artifact ids; raise ValueError if invalid."""
        if self.intent in ("tweak", "polish") and not target_artifact_id:
            raise ValueError(
                f"intent={self.intent!r} には target (pptxArtifactId) が必要です"
            )
        if self.style_source.kind == "from-ref" and not style_ref_artifact_id:
            raise ValueError(
                "style_source.kind='from-ref' には styleRefArtifactId が必要です"
            )


def parse_mode_spec(raw: str | None) -> ModeSpec | None:
    """Parse a JSON-encoded ModeSpec coming from a multipart form field.

    Returns None when the field is absent or empty (caller can then infer).
    Raises ValueError when JSON is malformed or schema validation fails.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"modeSpec is not valid JSON: {e}") from e
    try:
        return ModeSpec(**data)
    except ValidationError as e:
        raise ValueError(f"modeSpec failed validation: {e}") from e
