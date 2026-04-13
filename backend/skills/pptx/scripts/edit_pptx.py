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
    {"type":"add_paragraph", "slide":i, "shape":j, "text":"...", "align":"left|center|right|justify"}
    {"type":"add_run", "slide":i, "shape":j, "para":p, "text":"..."}
    {"type":"text_style", "slide":i, "shape":j, "para":p, "run":r,
     "bold":true/false, "italic":true/false, "font_size":PT, "font_name":"...",
     "color_r":R, "color_g":G, "color_b":B}
    {"type":"paragraph_align", "slide":i, "shape":j, "para":p, "align":"left|center|right|justify"}

  Image:
    {"type":"add_image", "slide":i, "image_base64":"...", "mime":"image/png",
     "x":X, "y":Y, "cx":CX, "cy":CY}

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
    shape = _get_shape(prs, op)
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(op["r"], op["g"], op["b"])


def op_fill_none(prs, op):
    _get_shape(prs, op).fill.background()


def op_transform(prs, op):
    shape = _get_shape(prs, op)
    shape.left = Emu(op["x"])
    shape.top = Emu(op["y"])
    shape.width = Emu(op["cx"])
    shape.height = Emu(op["cy"])
    shape.rotation = op.get("rot", 0) / 60000.0


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
    if "fill_r" in op and "fill_g" in op and "fill_b" in op:
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(op["fill_r"], op["fill_g"], op["fill_b"])
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

    dx = op.get("dx", 457200)  # default 0.5 inch
    dy = op.get("dy", 457200)
    xfrm = new_sp.find(f".//{qn('a:xfrm')}")
    if xfrm is not None:
        off = xfrm.find(qn("a:off"))
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

    align = op.get("align")
    if align:
        pp_align = ALIGN_MAP.get(align)
        if pp_align is not None:
            pPr = p.get_or_add_pPr()
            pPr.set("algn", _ALIGN_TO_OOXML.get(pp_align, "l"))


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
    run = runs[op["run"]]

    if "bold" in op:
        run.font.bold = bool(op["bold"])
    if "italic" in op:
        run.font.italic = bool(op["italic"])
    if "font_size" in op:
        run.font.size = Pt(op["font_size"])
    if "font_name" in op:
        run.font.name = op["font_name"]
    _apply_font_rgb(run.font, op)


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
    rId = slide_id.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    prs.part.drop_rel(rId)
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
    # Image
    "add_image": op_add_image,
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
