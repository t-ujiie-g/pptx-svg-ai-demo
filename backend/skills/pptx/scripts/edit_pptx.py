"""edit_pptx.py — Apply a batch of edits to an existing PPTX artifact.

Usage (via ADK run_skill_script):
    run_skill_script(
        skill_name="pptx",
        script_path="scripts/edit_pptx.py",
        script_args={
            "artifact_id": "abc-123",
            "ops": '<JSON string — see below>',
            "output_filename": "updated.pptx",
        },
    )

`ops` is a JSON string encoding a list of operations applied in order.
Each op's `slide` index refers to the presentation state AFTER previous ops.

Supported operations:

  Shape content:
    {"type":"text", "slide":i, "shape":j, "para":p, "run":r, "text":"..."}
    {"type":"fill", "slide":i, "shape":j, "r":R, "g":G, "b":B}
    {"type":"fill_none", "slide":i, "shape":j}
    {"type":"transform", "slide":i, "shape":j,
     "x":X, "y":Y, "cx":CX, "cy":CY, "rot":ROT}  # EMU; rot in 60000ths of deg
    {"type":"stroke", "slide":i, "shape":j,
     "r":R, "g":G, "b":B, "width":W, "dash":"solid|dash|dot|dashDot|lgDash"}
    {"type":"stroke_none", "slide":i, "shape":j}

  Shape CRUD:
    {"type":"add_shape", "slide":i, "shape_type":"rect|ellipse|roundRect|triangle",
     "x":X, "y":Y, "cx":CX, "cy":CY,
     "fill_r":R, "fill_g":G, "fill_b":B,
     "text":"...", "font_size":14, "font_name":"...", "font_bold":true,
     "color_r":R, "color_g":G, "color_b":B, "align":"center",
     "stroke_r":R, "stroke_g":G, "stroke_b":B, "stroke_width":W}
    {"type":"delete_shape", "slide":i, "shape":j}
    {"type":"duplicate_shape", "slide":i, "shape":j, "dx":DX, "dy":DY}

  Text editing:
    {"type":"add_paragraph", "slide":i, "shape":j, "text":"...",
     "align":"left|center|right|justify",
     "level":0..8, "bullet":"none|dot|number|<char>",
     "char":"•", "color_r":R, "color_g":G, "color_b":B}
    {"type":"add_run", "slide":i, "shape":j, "para":p, "text":"..."}
    {"type":"text_style", "slide":i, "shape":j, "para":p, "run":r,
     "bold":true/false, "italic":true/false, "font_size":PT, "font_name":"...",
     "color_r":R, "color_g":G, "color_b":B}
    {"type":"paragraph_align", "slide":i, "shape":j, "para":p, "align":"left|center|right|justify"}

  Image:
    {"type":"add_image", "slide":i, "image_base64":"...", "mime":"image/png",
     "x":X, "y":Y, "cx":CX, "cy":CY}

  Tables (graphicFrame containing a:tbl):
    {"type":"table_cell_text", "slide":i, "shape":j, "row":r, "col":c, "text":"..."}
    {"type":"table_cell_fill", "slide":i, "shape":j, "row":r, "col":c,
     "r":R, "g":G, "b":B}
    {"type":"table_cell_fill_none", "slide":i, "shape":j, "row":r, "col":c}
    {"type":"table_cell_style", "slide":i, "shape":j, "row":r, "col":c,
     "bold":..., "italic":..., "font_size":PT, "font_name":"...",
     "color_r":R, "color_g":G, "color_b":B, "align":"left|center|right|justify"}
    {"type":"add_table", "slide":i, "rows":R, "cols":C,
     "x":X, "y":Y, "cx":CX, "cy":CY,
     "data":[["a","b"],["c","d"]]}            # optional initial values
    {"type":"add_table_row", "slide":i, "shape":j, "after":r}   # default: last
    {"type":"delete_table_row", "slide":i, "shape":j, "row":r}

  Slide background:
    {"type":"slide_background", "slide":i, "r":R, "g":G, "b":B}
    {"type":"slide_background", "slide":i, "fill_none": true}

  Bullets / list level (existing paragraph; add_paragraph takes the same fields):
    {"type":"paragraph_bullet", "slide":i, "shape":j, "para":p,
     "bullet":"none|dot|number|<char>", "level":0..8,
     "char":"•", "color_r":R, "color_g":G, "color_b":B}

  Slide management:
    {"type":"duplicate_slide", "source":i, "insert_after":j}
    {"type":"delete_slide", "slide":i}
    {"type":"reorder_slides", "order":[2,0,1,3]}

Output (stdout, last line):
    __PPTX_ARTIFACT__ {"artifact_id":"...","filename":"...",
                       "size_bytes":N,"download_url":"/artifacts/..."}
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from copy import deepcopy

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from artifact_client import fetch_artifact, post_artifact, print_artifact_marker


# ──────────────────────────────────────────────────────────────────────
# Constants & helpers
# ──────────────────────────────────────────────────────────────────────

# Alignment: accept both full names and OOXML short codes
ALIGN_MAP = {
    "left": PP_ALIGN.LEFT,   "l": PP_ALIGN.LEFT,
    "center": PP_ALIGN.CENTER, "ctr": PP_ALIGN.CENTER,
    "right": PP_ALIGN.RIGHT,  "r": PP_ALIGN.RIGHT,
    "justify": PP_ALIGN.JUSTIFY, "just": PP_ALIGN.JUSTIFY,
}

# PP_ALIGN → OOXML short code (for oxml-level paragraph property)
_ALIGN_TO_OOXML = {
    PP_ALIGN.LEFT: "l", PP_ALIGN.CENTER: "ctr",
    PP_ALIGN.RIGHT: "r", PP_ALIGN.JUSTIFY: "just",
}

# Shape type string → MSO_SHAPE enum
_MSO_SHAPE_MAP = {
    "rect": MSO_SHAPE.RECTANGLE,
    "ellipse": MSO_SHAPE.OVAL,
    "roundRect": MSO_SHAPE.ROUNDED_RECTANGLE,
    "triangle": MSO_SHAPE.ISOSCELES_TRIANGLE,
    "diamond": MSO_SHAPE.DIAMOND,
    "pentagon": MSO_SHAPE.PENTAGON,
    "hexagon": MSO_SHAPE.HEXAGON,
    "star5": MSO_SHAPE.STAR_5_POINT,
    "rightArrow": MSO_SHAPE.RIGHT_ARROW,
    "leftArrow": MSO_SHAPE.LEFT_ARROW,
    "downArrow": MSO_SHAPE.DOWN_ARROW,
    "upArrow": MSO_SHAPE.UP_ARROW,
}

# Dash style string → MSO_LINE_DASH_STYLE int
_DASH_STYLE_MAP = {
    "dash": 2,
    "dot": 3,
    "dashDot": 5,
    "lgDash": 7,
}

# Bullet auto-numbering type aliases (input → OOXML buAutoNum/@type)
_BULLET_AUTO_NUM_TYPES = {
    "number": "arabicPeriod",
    "arabicPeriod": "arabicPeriod",
    "arabicParenR": "arabicParenR",
    "alphaUcPeriod": "alphaUcPeriod",
    "alphaLcPeriod": "alphaLcPeriod",
    "romanUcPeriod": "romanUcPeriod",
    "romanLcPeriod": "romanLcPeriod",
}

# OOXML stores rotation in 60_000ths of a degree.
_ROT_PER_DEGREE = 60000.0

# Default offset used when duplicate_shape doesn't specify dx/dy.
_DEFAULT_DUPLICATE_OFFSET_EMU = 457200  # 0.5 inch

# Default bullet character when bullet="dot" is given without an explicit char.
_DEFAULT_BULLET_CHAR = "•"


def _qa(tag: str) -> str:
    return qn(f"a:{tag}")


def _qp(tag: str) -> str:
    return qn(f"p:{tag}")


def _get_shape(prs, op):
    """Get shape by slide and shape index."""
    slide = prs.slides[op["slide"]]
    shapes = list(slide.shapes)
    idx = op["shape"]
    if idx < 0 or idx >= len(shapes):
        raise IndexError(f"shape index {idx} out of range (0..{len(shapes)-1})")
    return shapes[idx]


def _get_text_frame(prs, op):
    """Get text frame, raising if shape has none."""
    shape = _get_shape(prs, op)
    if not shape.has_text_frame:
        raise ValueError(f"shape {op['shape']} has no text frame")
    return shape.text_frame


def _apply_alignment(para, align_str):
    """Set paragraph alignment from string key."""
    pp_align = ALIGN_MAP.get(align_str)
    if pp_align is not None:
        para.alignment = pp_align


def _apply_font_rgb(font, op, r_key="color_r", g_key="color_g", b_key="color_b"):
    """Set font color from op dict if all three keys present."""
    if r_key in op and g_key in op and b_key in op:
        font.color.rgb = RGBColor(op[r_key], op[g_key], op[b_key])


def _apply_run_styles(run, op):
    """Apply font styles (bold/italic/size/name/color) from op dict onto a run."""
    if "bold" in op:
        run.font.bold = bool(op["bold"])
    if "italic" in op:
        run.font.italic = bool(op["italic"])
    if "font_size" in op:
        run.font.size = Pt(op["font_size"])
    if "font_name" in op:
        run.font.name = op["font_name"]
    _apply_font_rgb(run.font, op)


def _set_solid_fill(fill, r: int, g: int, b: int) -> None:
    """Set a python-pptx FillFormat to a solid RGB colour."""
    fill.solid()
    fill.fore_color.rgb = RGBColor(r, g, b)


def _get_table(prs, op):
    """Return the python-pptx Table for a graphicFrame shape, else raise."""
    shape = _get_shape(prs, op)
    if not getattr(shape, "has_table", False):
        raise ValueError(f"shape {op['shape']} on slide {op['slide']} has no table")
    return shape.table


def _hex_rgb(r: int, g: int, b: int) -> str:
    return f"{r & 0xFF:02X}{g & 0xFF:02X}{b & 0xFF:02X}"


# Order of children allowed inside <a:pPr> per OOXML — used to keep
# bullet-related elements schema-valid when we re-insert them.
_PPR_TAIL_TAGS = ("defRPr", "extLst")


def _insert_before_tail(pPr, child) -> None:
    """Insert child before any tail element (defRPr/extLst) inside pPr."""
    for tag in _PPR_TAIL_TAGS:
        anchor = pPr.find(_qa(tag))
        if anchor is not None:
            anchor.addprevious(child)
            return
    pPr.append(child)


def _set_bullet_on_pPr(pPr, bullet, *, char=None, color=None) -> None:
    """Apply bullet style on a pPr element.

    bullet:
        "none"        → <a:buNone/>
        "dot"         → <a:buChar char="•"/> (or `char` if given)
        "number"/...  → <a:buAutoNum type="arabicPeriod"/>
        any other str → treated as a literal bullet character
    color: optional (r,g,b) tuple for bullet color (<a:buClr>).
    """
    # Strip every existing bullet-related child first
    for tag in ("buClr", "buSzTx", "buSzPct", "buSzPts",
                "buFontTx", "buFont", "buNone", "buAutoNum", "buChar"):
        for el in pPr.findall(_qa(tag)):
            pPr.remove(el)

    if color is not None:
        buClr = etree.Element(_qa("buClr"))
        etree.SubElement(buClr, _qa("srgbClr"), val=_hex_rgb(*color))
        _insert_before_tail(pPr, buClr)

    if bullet == "none":
        _insert_before_tail(pPr, etree.Element(_qa("buNone")))
        return

    if bullet in _BULLET_AUTO_NUM_TYPES:
        el = etree.Element(_qa("buAutoNum"))
        el.set("type", _BULLET_AUTO_NUM_TYPES[bullet])
        _insert_before_tail(pPr, el)
        return

    # Treat as bullet character — "dot" → default char, anything else → literal
    bullet_char = char or (_DEFAULT_BULLET_CHAR if bullet == "dot" else bullet)
    el = etree.Element(_qa("buChar"))
    el.set("char", bullet_char)
    _insert_before_tail(pPr, el)


def _apply_paragraph_props(p, op) -> None:
    """Apply align / level / bullet on the given <a:p> element."""
    pPr = None

    align = op.get("align")
    if align:
        pp_align = ALIGN_MAP.get(align)
        if pp_align is not None:
            pPr = p.get_or_add_pPr()
            pPr.set("algn", _ALIGN_TO_OOXML.get(pp_align, "l"))

    if "level" in op:
        pPr = pPr if pPr is not None else p.get_or_add_pPr()
        pPr.set("lvl", str(int(op["level"])))

    if "bullet" in op:
        pPr = pPr if pPr is not None else p.get_or_add_pPr()
        color = None
        if all(k in op for k in ("color_r", "color_g", "color_b")):
            color = (op["color_r"], op["color_g"], op["color_b"])
        _set_bullet_on_pPr(pPr, op["bullet"], char=op.get("char"), color=color)


# ──────────────────────────────────────────────────────────────────────
# Shape content operations
# ──────────────────────────────────────────────────────────────────────


def op_text(prs, op):
    tf = _get_text_frame(prs, op)
    para = tf.paragraphs[op["para"]]
    runs = list(para.runs)
    if not runs:
        raise ValueError(f"paragraph {op['para']} has no runs in shape {op['shape']}")
    runs[op["run"]].text = op["text"]


def op_fill(prs, op):
    _set_solid_fill(_get_shape(prs, op).fill, op["r"], op["g"], op["b"])


def op_fill_none(prs, op):
    _get_shape(prs, op).fill.background()


def op_transform(prs, op):
    shape = _get_shape(prs, op)
    shape.left = Emu(op["x"])
    shape.top = Emu(op["y"])
    shape.width = Emu(op["cx"])
    shape.height = Emu(op["cy"])
    shape.rotation = op.get("rot", 0) / _ROT_PER_DEGREE


def op_stroke(prs, op):
    shape = _get_shape(prs, op)
    shape.line.color.rgb = RGBColor(op["r"], op["g"], op["b"])
    if "width" in op:
        shape.line.width = Emu(op["width"])
    dash = op.get("dash", "solid")
    if dash and dash != "solid":
        shape.line.dash_style = _DASH_STYLE_MAP.get(dash)


def op_stroke_none(prs, op):
    _get_shape(prs, op).line.fill.background()


# ──────────────────────────────────────────────────────────────────────
# Shape CRUD operations
# ──────────────────────────────────────────────────────────────────────


def op_add_shape(prs, op):
    slide = prs.slides[op["slide"]]
    shape_name = op.get("shape_type", "rect")
    auto_shape_type = _MSO_SHAPE_MAP.get(shape_name)
    if auto_shape_type is None:
        raise ValueError(f"unknown shape_type: {shape_name}")

    shape = slide.shapes.add_shape(
        auto_shape_type,
        Emu(op["x"]), Emu(op["y"]),
        Emu(op["cx"]), Emu(op["cy"]),
    )

    # Optional fill
    if all(k in op for k in ("fill_r", "fill_g", "fill_b")):
        _set_solid_fill(shape.fill, op["fill_r"], op["fill_g"], op["fill_b"])
    elif op.get("fill_none"):
        shape.fill.background()

    # Optional stroke
    if "stroke_r" in op:
        shape.line.color.rgb = RGBColor(op["stroke_r"], op["stroke_g"], op["stroke_b"])
        if "stroke_width" in op:
            shape.line.width = Emu(op["stroke_width"])

    # Optional text
    text = op.get("text")
    if text is not None:
        tf = shape.text_frame
        tf.word_wrap = True
        para = tf.paragraphs[0]
        para.text = text
        if para.runs:
            run = para.runs[0]
            if "font_size" in op:
                run.font.size = Pt(op["font_size"])
            if "font_name" in op:
                run.font.name = op["font_name"]
            if "font_bold" in op:
                run.font.bold = bool(op["font_bold"])
            _apply_font_rgb(run.font, op)
        if "align" in op:
            _apply_alignment(para, op["align"])

    return f"OK:added shape_idx={len(list(slide.shapes))-1}"


def op_delete_shape(prs, op):
    shape = _get_shape(prs, op)
    shape.element.getparent().remove(shape.element)


def op_duplicate_shape(prs, op):
    shape = _get_shape(prs, op)
    slide = prs.slides[op["slide"]]

    new_sp = deepcopy(shape.element)
    slide.shapes._spTree.append(new_sp)

    dx = op.get("dx", _DEFAULT_DUPLICATE_OFFSET_EMU)
    dy = op.get("dy", _DEFAULT_DUPLICATE_OFFSET_EMU)
    xfrm = new_sp.find(f".//{_qa('xfrm')}")
    if xfrm is not None:
        off = xfrm.find(_qa("off"))
        if off is not None:
            off.set("x", str(int(off.get("x", "0")) + dx))
            off.set("y", str(int(off.get("y", "0")) + dy))

    return f"OK:new_shape_idx={len(list(slide.shapes))-1}"


# ──────────────────────────────────────────────────────────────────────
# Text editing operations
# ──────────────────────────────────────────────────────────────────────


def op_add_paragraph(prs, op):
    tf = _get_text_frame(prs, op)
    p = tf._txBody.add_p()
    run = p.add_r()
    run.text = op.get("text", "")
    _apply_paragraph_props(p, op)


def op_paragraph_bullet(prs, op):
    tf = _get_text_frame(prs, op)
    para = tf.paragraphs[op["para"]]
    _apply_paragraph_props(para._p, op)


def op_add_run(prs, op):
    tf = _get_text_frame(prs, op)
    para = tf.paragraphs[op["para"]]
    r = para._p.add_r()
    r.text = op.get("text", "")


def op_text_style(prs, op):
    tf = _get_text_frame(prs, op)
    para = tf.paragraphs[op["para"]]
    runs = list(para.runs)
    if not runs:
        raise ValueError(f"paragraph {op['para']} has no runs")
    _apply_run_styles(runs[op["run"]], op)


def op_paragraph_align(prs, op):
    tf = _get_text_frame(prs, op)
    _apply_alignment(tf.paragraphs[op["para"]], op.get("align", "left"))


# ──────────────────────────────────────────────────────────────────────
# Image operations
# ──────────────────────────────────────────────────────────────────────


def op_add_image(prs, op):
    slide = prs.slides[op["slide"]]
    image_data = base64.b64decode(op["image_base64"])
    slide.shapes.add_picture(
        io.BytesIO(image_data),
        Emu(op["x"]), Emu(op["y"]),
        Emu(op["cx"]), Emu(op["cy"]),
    )


# ──────────────────────────────────────────────────────────────────────
# Slide management operations
# ──────────────────────────────────────────────────────────────────────


def op_duplicate_slide(prs, op):
    """Deep-copy a slide and its shapes; optionally reposition it."""
    source = prs.slides[op["source"]]
    new_slide = prs.slides.add_slide(source.slide_layout)

    for shp in list(new_slide.shapes):
        shp.element.getparent().remove(shp.element)

    for shp in source.shapes:
        new_slide.shapes._spTree.insert_element_before(
            deepcopy(shp.element), "p:extLst",
        )

    for rel in source.part.rels.values():
        if "notesSlide" in rel.reltype:
            continue
        new_slide.part.rels.get_or_add(rel.reltype, rel._target)

    insert_after = op.get("insert_after")
    if insert_after is not None:
        sldIdLst = prs.slides._sldIdLst
        sld_ids = list(sldIdLst)
        new_id = sld_ids[-1]
        sldIdLst.remove(new_id)
        target_pos = insert_after + 1
        if target_pos >= len(sld_ids):
            sldIdLst.append(new_id)
        else:
            sldIdLst.insert(target_pos, new_id)


def op_delete_slide(prs, op):
    """Remove slide at given index."""
    slide_id = prs.slides._sldIdLst[op["slide"]]
    rel_id = slide_id.get(qn("r:id"))
    prs.part.drop_rel(rel_id)
    prs.slides._sldIdLst.remove(slide_id)


def op_reorder_slides(prs, op):
    """Reorder slides according to the given order array."""
    new_order = op["order"]
    sldIdLst = prs.slides._sldIdLst
    sld_ids = list(sldIdLst)

    if sorted(new_order) != list(range(len(sld_ids))):
        raise ValueError(
            f"order must be a permutation of 0..{len(sld_ids)-1}, got {new_order}"
        )

    for sid in sld_ids:
        sldIdLst.remove(sid)
    for idx in new_order:
        sldIdLst.append(sld_ids[idx])


# ──────────────────────────────────────────────────────────────────────
# Table operations
# ──────────────────────────────────────────────────────────────────────


def op_table_cell_text(prs, op):
    cell = _get_table(prs, op).cell(op["row"], op["col"])
    cell.text = op.get("text", "")


def op_table_cell_fill(prs, op):
    cell = _get_table(prs, op).cell(op["row"], op["col"])
    _set_solid_fill(cell.fill, op["r"], op["g"], op["b"])


def op_table_cell_fill_none(prs, op):
    _get_table(prs, op).cell(op["row"], op["col"]).fill.background()


def op_table_cell_style(prs, op):
    cell = _get_table(prs, op).cell(op["row"], op["col"])
    for para in cell.text_frame.paragraphs:
        if "align" in op:
            _apply_alignment(para, op["align"])
        for run in para.runs:
            _apply_run_styles(run, op)


def op_add_table(prs, op):
    slide = prs.slides[op["slide"]]
    rows = int(op["rows"])
    cols = int(op["cols"])
    if rows < 1 or cols < 1:
        raise ValueError("rows and cols must be >= 1")

    graphic_frame = slide.shapes.add_table(
        rows, cols,
        Emu(op["x"]), Emu(op["y"]),
        Emu(op["cx"]), Emu(op["cy"]),
    )

    data = op.get("data")
    if data:
        table = graphic_frame.table
        for r, row in enumerate(data):
            if r >= rows:
                break
            for c, val in enumerate(row):
                if c >= cols:
                    break
                if val is not None:
                    table.cell(r, c).text = str(val)

    return f"OK:added table_shape_idx={len(list(slide.shapes))-1}"


def _table_rows_xml(table):
    """Return (tbl element, list of <a:tr> children)."""
    tbl = table._tbl
    return tbl, tbl.findall(_qa("tr"))


def _clear_cell_text(tc) -> None:
    """Clear text content inside a <a:tc> while preserving paragraph properties."""
    tx_body = tc.find(_qa("txBody"))
    if tx_body is None:
        return
    for p in tx_body.findall(_qa("p")):
        for child in list(p):
            if child.tag != _qa("pPr"):
                p.remove(child)


def op_add_table_row(prs, op):
    _, rows_xml = _table_rows_xml(_get_table(prs, op))
    if not rows_xml:
        raise ValueError("table has no rows to copy from")

    after = op.get("after", len(rows_xml) - 1)
    if after < 0 or after >= len(rows_xml):
        raise IndexError(f"after={after} out of range (0..{len(rows_xml)-1})")

    src = rows_xml[after]
    new_row = deepcopy(src)
    for tc in new_row.findall(_qa("tc")):
        _clear_cell_text(tc)
    src.addnext(new_row)
    return f"OK:row_idx={after+1}"


def op_delete_table_row(prs, op):
    tbl, rows_xml = _table_rows_xml(_get_table(prs, op))
    idx = op["row"]
    if idx < 0 or idx >= len(rows_xml):
        raise IndexError(f"row {idx} out of range (0..{len(rows_xml)-1})")
    tbl.remove(rows_xml[idx])


# ──────────────────────────────────────────────────────────────────────
# Slide background
# ──────────────────────────────────────────────────────────────────────


def op_slide_background(prs, op):
    slide = prs.slides[op["slide"]]
    cSld = slide._element.find(_qp("cSld"))
    if cSld is None:
        raise ValueError("slide has no cSld element")

    # Strip any existing background; cSld must contain at most one <p:bg>.
    for existing in cSld.findall(_qp("bg")):
        cSld.remove(existing)

    if op.get("fill_none"):
        return  # cleared, inherit master/layout

    if not all(k in op for k in ("r", "g", "b")):
        raise ValueError("slide_background requires r,g,b or fill_none:true")

    bg = etree.Element(_qp("bg"))
    bgPr = etree.SubElement(bg, _qp("bgPr"))
    solidFill = etree.SubElement(bgPr, _qa("solidFill"))
    etree.SubElement(solidFill, _qa("srgbClr"), val=_hex_rgb(op["r"], op["g"], op["b"]))
    # <p:bg> must be the first child of <p:cSld>.
    cSld.insert(0, bg)


# ──────────────────────────────────────────────────────────────────────
# Handler registry
# ──────────────────────────────────────────────────────────────────────

OP_HANDLERS = {
    # Shape content
    "text": op_text,
    "fill": op_fill,
    "fill_none": op_fill_none,
    "transform": op_transform,
    "stroke": op_stroke,
    "stroke_none": op_stroke_none,
    # Shape CRUD
    "add_shape": op_add_shape,
    "delete_shape": op_delete_shape,
    "duplicate_shape": op_duplicate_shape,
    # Text editing
    "add_paragraph": op_add_paragraph,
    "add_run": op_add_run,
    "text_style": op_text_style,
    "paragraph_align": op_paragraph_align,
    "paragraph_bullet": op_paragraph_bullet,
    # Image
    "add_image": op_add_image,
    # Tables
    "table_cell_text": op_table_cell_text,
    "table_cell_fill": op_table_cell_fill,
    "table_cell_fill_none": op_table_cell_fill_none,
    "table_cell_style": op_table_cell_style,
    "add_table": op_add_table,
    "add_table_row": op_add_table_row,
    "delete_table_row": op_delete_table_row,
    # Slide background
    "slide_background": op_slide_background,
    # Slide management
    "duplicate_slide": op_duplicate_slide,
    "delete_slide": op_delete_slide,
    "reorder_slides": op_reorder_slides,
}


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact_id", required=True)
    ap.add_argument("--ops", required=True, help="JSON array of ops")
    ap.add_argument("--output_filename", default="updated.pptx")
    args = ap.parse_args()

    try:
        ops = json.loads(args.ops)
    except json.JSONDecodeError as e:
        print(f"ERROR: --ops is not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(ops, list):
        print("ERROR: --ops must be a JSON array", file=sys.stderr)
        sys.exit(2)

    pptx_bytes = fetch_artifact(args.artifact_id)
    prs = Presentation(io.BytesIO(pptx_bytes))

    applied = []
    for i, op in enumerate(ops):
        t = op.get("type")
        handler = OP_HANDLERS.get(t)
        if handler is None:
            applied.append({"index": i, "ok": False, "error": f"unknown op type: {t}"})
            continue
        try:
            result = handler(prs, op)
            entry = {"index": i, "ok": True, "type": t}
            if result:
                entry["result"] = result
            applied.append(entry)
        except Exception as e:
            applied.append({
                "index": i, "ok": False, "type": t,
                "error": f"{type(e).__name__}: {e}",
            })

    buf = io.BytesIO()
    prs.save(buf)

    filename = args.output_filename
    if not filename.endswith(".pptx"):
        filename += ".pptx"

    result = post_artifact(buf.getvalue(), filename, args.artifact_id)

    print(json.dumps({"applied": applied}, ensure_ascii=False))
    print_artifact_marker(result)


if __name__ == "__main__":
    main()
