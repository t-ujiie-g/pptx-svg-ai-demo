"""StyleSpec — abstract style (Layer A) + reusable slide templates (Layer B).

Phase 2 extracts both layers from a PPTX so downstream generation can:
  - Layer A: copy palette/font/spacing into new generations (`from-target`/`from-ref`/`mix`)
  - Layer B: lift specific slide templates (cover, section divider, closing, ...)
            and reuse them with placeholder text-substitution.

Used as the response_schema for the Gemini structured-output call in
`services/style_extractor.py`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.constants import (
    PPTX_ROLE_STYLE_REF,
    PPTX_ROLE_TARGET,
    PptxContextRole,
)

# ──────────────────────────────────────────────────────────────────
# Layer A — abstract style (palette / typography / geometry / decoration)
# ──────────────────────────────────────────────────────────────────


class Palette(BaseModel):
    primary: str = Field(description="6-hex like '#1E2761' — dominant brand colour")
    secondary: str
    accent: str
    bg_light: str = Field(description="6-hex — light/cream background")
    bg_dark: str = Field(description="6-hex — dark/navy background")
    text_main: str
    text_sub: str
    dominance: Literal["primary", "secondary", "accent", "bg_light", "bg_dark"] = Field(
        description="どの色が60-70%の視覚比率を占めるか"
    )


class Typography(BaseModel):
    header_font: str
    body_font: str
    title_pt: int = Field(ge=8, le=120)
    section_pt: int = Field(ge=8, le=80)
    body_pt: int = Field(ge=6, le=40)
    caption_pt: int = Field(ge=6, le=30)


class Geometry(BaseModel):
    margin_emu: int = Field(description="Outer margin in EMU (914400 = 1 inch)")
    block_gap_emu: int = Field(description="Gap between content blocks in EMU")
    slide_w_emu: int
    slide_h_emu: int


class Decoration(BaseModel):
    motif: Literal[
        "rounded-cards", "side-bar", "icon-circles",
        "thick-borders", "gradient-bg", "minimal", "none",
    ] = "none"
    uses_accent_lines: bool = False
    uses_dark_title: bool = False


class LayerA(BaseModel):
    palette: Palette
    typography: Typography
    geometry: Geometry
    decoration: Decoration
    tone_tags: list[str] = Field(
        default_factory=list,
        description="例: ['executive','calm','technical','playful'] (最大5個)",
    )


# ──────────────────────────────────────────────────────────────────
# Layer B — reusable slide templates (with role-tagged shapes)
# ──────────────────────────────────────────────────────────────────


# 各shapeの「役割」。生成側で意味付けして再利用するためのタグ。
ShapeRole = Literal[
    "title", "subtitle", "body", "bullet_list", "caption",
    "decoration", "image_slot", "icon",
    "stat_number", "stat_label",
    "footer", "page_number", "logo", "other",
]

# fillの色タグ。具体hexはpaletteから引く。
FillRole = Literal["primary", "secondary", "accent", "bg_light", "bg_dark", "none"]

# テンプレ化したスライドの種類。
TemplateKind = Literal[
    "cover", "section_divider", "agenda", "closing",
    "content_two_col", "content_grid", "content_one_col",
    "stat_callout", "comparison", "timeline", "other",
]


class TemplateShape(BaseModel):
    role: ShapeRole
    x_emu: int
    y_emu: int
    cx_emu: int
    cy_emu: int
    rot: int = 0
    fill_role: FillRole = "none"
    text_template: str | None = Field(
        default=None,
        description=(
            "プレースホルダ式テキストテンプレート。例: '<<TITLE>>' / "
            "'<<BULLET_1>>' / '<<STAT_NUMBER>>'。テキストshapeのみ。"
        ),
    )
    font_role: Literal["header", "body", "caption", "none"] = "none"
    font_pt: int | None = None
    align: Literal["left", "center", "right", "justify"] | None = None
    is_decoration: bool = False


class SlideTemplate(BaseModel):
    kind: TemplateKind
    source_slide_idx: int = Field(description="抽出元のスライドindex (0-based)")
    shapes: list[TemplateShape]


class LayerB(BaseModel):
    slides: list[SlideTemplate] = Field(
        default_factory=list,
        description=(
            "再利用に値するスライドテンプレートのみ。本文ページが似通っている場合は"
            "代表1枚のみを content_* として登録。同一kindは原則1枚ずつ。"
        ),
    )


# ──────────────────────────────────────────────────────────────────
# StyleSpec — top-level container
# ──────────────────────────────────────────────────────────────────


class StyleSpec(BaseModel):
    """Top-level style specification used as Gemini's response_schema."""

    version: int = 1
    layer_a: LayerA
    layer_b: LayerB

    def to_compact_block(
        self,
        *,
        source_artifact_id: str,
        role: PptxContextRole,
    ) -> str:
        """Render a Japanese context block to inject into the user message.

        `role` describes what this style spec is for (the editing target or a
        reference for style only).
        """
        if role not in (PPTX_ROLE_TARGET, PPTX_ROLE_STYLE_REF):
            raise ValueError(f"Unknown PPTX context role: {role!r}")
        a = self.layer_a
        header = (
            f"【スタイル仕様 ({role}) — artifact_id: {source_artifact_id}】"
        )
        # Layer A コンパクト要約
        palette_line = (
            f"palette: primary={a.palette.primary}, secondary={a.palette.secondary}, "
            f"accent={a.palette.accent}, bg_light={a.palette.bg_light}, "
            f"bg_dark={a.palette.bg_dark}, text_main={a.palette.text_main}, "
            f"text_sub={a.palette.text_sub}, dominance={a.palette.dominance}"
        )
        typo_line = (
            f"typography: header_font={a.typography.header_font!r}, "
            f"body_font={a.typography.body_font!r}, "
            f"title_pt={a.typography.title_pt}, section_pt={a.typography.section_pt}, "
            f"body_pt={a.typography.body_pt}, caption_pt={a.typography.caption_pt}"
        )
        geom_line = (
            f"geometry: margin_emu={a.geometry.margin_emu}, "
            f"block_gap_emu={a.geometry.block_gap_emu}, "
            f"slide={a.geometry.slide_w_emu}x{a.geometry.slide_h_emu} EMU"
        )
        deco_line = (
            f"decoration: motif={a.decoration.motif}, "
            f"accent_lines={a.decoration.uses_accent_lines}, "
            f"dark_title={a.decoration.uses_dark_title}"
        )
        tone_line = f"tone_tags: {a.tone_tags}"

        # Layer B — shape 座標まで含めた完全なテンプレート定義を渡す。
        # cover/closing 等を「踏襲」するには配置情報が必須。
        b_lines = ["templates:"]
        if not self.layer_b.slides:
            b_lines.append("  (なし)")
        else:
            for tmpl in self.layer_b.slides:
                b_lines.append(
                    f"  ◆ kind={tmpl.kind} (元 slide={tmpl.source_slide_idx}):"
                )
                for sh in tmpl.shapes:
                    b_lines.append(_render_template_shape(sh))

        return "\n".join([header, palette_line, typo_line, geom_line, deco_line,
                          tone_line, *b_lines])


def _render_template_shape(sh: TemplateShape) -> str:
    """Render one Layer B shape into a single deterministic line.

    Includes everything an agent needs to reproduce the shape in PptxGenJS or
    python-pptx: position/size in EMU, rotation, fill_role (paletteから引く),
    font_role + font_pt, alignment, text_template, decoration flag.
    """
    parts = [
        f"    - role={sh.role}",
        f"pos=({sh.x_emu},{sh.y_emu})",
        f"size=({sh.cx_emu},{sh.cy_emu})",
    ]
    if sh.rot:
        parts.append(f"rot={sh.rot}")
    if sh.fill_role and sh.fill_role != "none":
        parts.append(f"fill={sh.fill_role}")
    if sh.font_role and sh.font_role != "none":
        font_str = f"font={sh.font_role}"
        if sh.font_pt:
            font_str += f"@{sh.font_pt}pt"
        parts.append(font_str)
    if sh.align:
        parts.append(f"align={sh.align}")
    if sh.text_template:
        parts.append(f"text={sh.text_template!r}")
    if sh.is_decoration:
        parts.append("[装飾]")
    return " ".join(parts)
