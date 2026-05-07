"""Mode/3-slot model for PPTX generation precision (Phase 1)."""

from src.agents.mode.inferrer import infer_mode_spec
from src.agents.mode.schema import (
    Intent,
    ModeSpec,
    StylePreset,
    StyleSource,
    StyleSourceKind,
    parse_mode_spec,
)

__all__ = [
    "Intent",
    "ModeSpec",
    "StyleSource",
    "StyleSourceKind",
    "StylePreset",
    "parse_mode_spec",
    "infer_mode_spec",
]
