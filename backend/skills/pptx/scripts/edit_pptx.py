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
  {"type":"text", "slide":i, "shape":j, "para":p, "run":r, "text":"..."}
  {"type":"fill", "slide":i, "shape":j, "r":R, "g":G, "b":B}
  {"type":"transform", "slide":i, "shape":j,
   "x":X, "y":Y, "cx":CX, "cy":CY, "rot":ROT}  # EMU; rot in 60000ths of deg
  {"type":"duplicate_slide", "source":i, "insert_after":j}
      # Deep-copies slide `source`; new slide goes at insert_after+1 (or end).
  {"type":"delete_slide", "slide":i}

Output (stdout, last line):
    __PPTX_ARTIFACT__ {"artifact_id":"...","filename":"...",
                       "size_bytes":N,"download_url":"/artifacts/..."}

The preceding stdout lines contain a per-op applied report.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from copy import deepcopy

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from artifact_client import fetch_artifact, post_artifact, print_artifact_marker


# ──────────────────────────────────────────────────────────────────────
# python-pptx operations
# ──────────────────────────────────────────────────────────────────────


def op_text(prs, op):
    slide = prs.slides[op["slide"]]
    shape = list(slide.shapes)[op["shape"]]
    if not shape.has_text_frame:
        raise ValueError(f"shape {op['shape']} has no text frame")
    tf = shape.text_frame
    para = tf.paragraphs[op["para"]]
    runs = list(para.runs)
    if not runs:
        raise ValueError(
            f"paragraph {op['para']} has no runs in shape {op['shape']}"
        )
    runs[op["run"]].text = op["text"]


def op_fill(prs, op):
    slide = prs.slides[op["slide"]]
    shape = list(slide.shapes)[op["shape"]]
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(op["r"], op["g"], op["b"])


def op_transform(prs, op):
    slide = prs.slides[op["slide"]]
    shape = list(slide.shapes)[op["shape"]]
    shape.left = Emu(op["x"])
    shape.top = Emu(op["y"])
    shape.width = Emu(op["cx"])
    shape.height = Emu(op["cy"])
    rot = op.get("rot", 0)
    # python-pptx uses degrees; we take OOXML 60000ths.
    shape.rotation = rot / 60000.0


def op_duplicate_slide(prs, op):
    """Deep-copy a slide and its shapes; optionally reposition it."""
    source_idx = op["source"]
    source = prs.slides[source_idx]

    # Create a new slide using the same layout.
    new_slide = prs.slides.add_slide(source.slide_layout)

    # Remove default placeholders added by the layout so the new slide starts empty.
    for shp in list(new_slide.shapes):
        shp.element.getparent().remove(shp.element)

    # Deep-copy all shapes from the source.
    for shp in source.shapes:
        new_slide.shapes._spTree.insert_element_before(deepcopy(shp.element), "p:extLst")

    # Copy relationships (for images, hyperlinks, etc.) skipping notesSlide.
    for rel in source.part.rels.values():
        if "notesSlide" in rel.reltype:
            continue
        new_slide.part.rels.get_or_add(rel.reltype, rel._target)

    # Reposition in sldIdLst if insert_after is given.
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
    """Remove slide at given index from the presentation."""
    slide_idx = op["slide"]
    slide_id = prs.slides._sldIdLst[slide_idx]
    rId = slide_id.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    prs.part.drop_rel(rId)
    prs.slides._sldIdLst.remove(slide_id)


OP_HANDLERS = {
    "text": op_text,
    "fill": op_fill,
    "transform": op_transform,
    "duplicate_slide": op_duplicate_slide,
    "delete_slide": op_delete_slide,
}


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-id", required=True)
    ap.add_argument("--ops", required=True, help="JSON array of ops")
    ap.add_argument("--output-filename", default="updated.pptx")
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
            handler(prs, op)
            applied.append({"index": i, "ok": True, "type": t})
        except Exception as e:
            applied.append({
                "index": i, "ok": False, "type": t,
                "error": f"{type(e).__name__}: {e}",
            })

    # Save to buffer and upload.
    buf = io.BytesIO()
    prs.save(buf)
    new_bytes = buf.getvalue()

    filename = args.output_filename
    if not filename.endswith(".pptx"):
        filename += ".pptx"

    result = post_artifact(new_bytes, filename, args.artifact_id)

    # Report per-op status (for LLM to see).
    print(json.dumps({"applied": applied}, ensure_ascii=False))
    # Marker line for chat.py SSE dispatcher.
    print_artifact_marker(result)


if __name__ == "__main__":
    main()
