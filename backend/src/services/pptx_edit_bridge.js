/**
 * pptx-svg Node.js JSON-RPC bridge.
 *
 * Long-running process that holds PptxRenderer instances keyed by session ID.
 * Communicates with the Python wrapper via line-delimited JSON over stdin/stdout.
 *
 * Protocol:
 *   stdin  -> {"id": 1, "method": "load_pptx", "params": {"session_id": "abc", "base64": "..."}}
 *   stdout <- {"id": 1, "result": {"slide_count": 5}} | {"id": 1, "error": "..."}
 */

const { PptxRenderer, findShapeElement, getShapeTransform, emuToPx } = require("pptx-svg");
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

// Session map: session_id -> { renderer, slideCount }
const sessions = new Map();

// Wasm binary — read once, reuse for all renderers
let wasmBuffer = null;

function getWasmBuffer() {
  if (!wasmBuffer) {
    const wasmPath = require.resolve("pptx-svg/dist/main.wasm");
    wasmBuffer = fs.readFileSync(wasmPath).buffer;
  }
  return wasmBuffer;
}

// --- SVG parsing to extract structured shape info ---

function parseSvgShapes(svgString) {
  const dom = new JSDOM(svgString, { contentType: "image/svg+xml" });
  const doc = dom.window.document;
  const svgEl = doc.querySelector("svg");
  if (!svgEl) return { shapes: [], slide_width_emu: 0, slide_height_emu: 0 };

  const slideCx = parseInt(svgEl.getAttribute("data-ooxml-slide-cx") || "9144000", 10);
  const slideCy = parseInt(svgEl.getAttribute("data-ooxml-slide-cy") || "6858000", 10);

  const shapeGs = doc.querySelectorAll("g[data-ooxml-shape-idx]");
  const shapes = [];

  for (const g of shapeGs) {
    const idx = parseInt(g.getAttribute("data-ooxml-shape-idx") || "-1", 10);
    const shapeType = g.getAttribute("data-ooxml-shape-type") || "?";
    const geom = g.getAttribute("data-ooxml-geom") || "";
    const fillHex = g.getAttribute("data-ooxml-fill") || "";

    // Position from data attributes
    const x = parseInt(g.getAttribute("data-ooxml-x") || "0", 10);
    const y = parseInt(g.getAttribute("data-ooxml-y") || "0", 10);
    const cx = parseInt(g.getAttribute("data-ooxml-cx") || "0", 10);
    const cy = parseInt(g.getAttribute("data-ooxml-cy") || "0", 10);
    const rot = parseInt(g.getAttribute("data-ooxml-rot") || "0", 10);

    // Extract text runs
    const textRuns = [];
    const runTspans = g.querySelectorAll("tspan[data-ooxml-run-idx]");
    const seen = new Map();
    for (const ts of runTspans) {
      const ri = ts.getAttribute("data-ooxml-run-idx");
      const paraTspan = ts.closest("tspan[data-ooxml-para-idx]");
      const pi = paraTspan ? paraTspan.getAttribute("data-ooxml-para-idx") : null;
      if (pi === null || ri === null) continue;
      const key = `${pi}:${ri}`;
      if (seen.has(key)) {
        textRuns[seen.get(key)].text += ts.textContent || "";
      } else {
        seen.set(key, textRuns.length);
        textRuns.push({ pi: parseInt(pi), ri: parseInt(ri), text: ts.textContent || "" });
      }
    }

    shapes.push({
      idx,
      shape_type: shapeType,
      geom: geom || undefined,
      fill_hex: fillHex.length === 6 ? fillHex : undefined,
      x, y, cx, cy, rot,
      text_runs: textRuns.length > 0 ? textRuns : undefined,
    });
  }

  return { shapes, slide_width_emu: slideCx, slide_height_emu: slideCy };
}

// --- RPC handlers ---

const handlers = {
  async load_pptx({ session_id, base64 }) {
    const buffer = Buffer.from(base64, "base64");
    const renderer = new PptxRenderer({ logLevel: "error" });
    await renderer.init(getWasmBuffer());
    const { slideCount } = await renderer.loadPptx(buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength));
    sessions.set(session_id, { renderer, slideCount });
    return { slide_count: slideCount };
  },

  async get_slide_info({ session_id, slide_idx }) {
    const sess = sessions.get(session_id);
    if (!sess) throw new Error(`Session not found: ${session_id}`);
    const svgString = sess.renderer.renderSlideSvg(slide_idx);
    if (svgString.startsWith("ERROR:")) throw new Error(svgString);
    const info = parseSvgShapes(svgString);
    return { slide_idx, ...info, svg: svgString };
  },

  async get_all_slides_info({ session_id }) {
    const sess = sessions.get(session_id);
    if (!sess) throw new Error(`Session not found: ${session_id}`);
    const slides = [];
    for (let i = 0; i < sess.slideCount; i++) {
      const svgString = sess.renderer.renderSlideSvg(i);
      if (svgString.startsWith("ERROR:")) {
        slides.push({ slide_idx: i, error: svgString });
        continue;
      }
      const info = parseSvgShapes(svgString);
      // Don't include SVG in bulk response to keep payload small
      slides.push({ slide_idx: i, ...info });
    }
    return { slide_count: sess.slideCount, slides };
  },

  async update_shape_text({ session_id, slide_idx, shape_idx, para_idx, run_idx, text }) {
    const sess = sessions.get(session_id);
    if (!sess) throw new Error(`Session not found: ${session_id}`);
    const result = sess.renderer.updateShapeText(slide_idx, shape_idx, para_idx, run_idx, text);
    if (result.startsWith("ERROR:")) throw new Error(result);
    return { ok: true };
  },

  async update_shape_fill({ session_id, slide_idx, shape_idx, r, g, b }) {
    const sess = sessions.get(session_id);
    if (!sess) throw new Error(`Session not found: ${session_id}`);
    const result = sess.renderer.updateShapeFill(slide_idx, shape_idx, r, g, b);
    if (result.startsWith("ERROR:")) throw new Error(result);
    return { ok: true };
  },

  async update_shape_transform({ session_id, slide_idx, shape_idx, x, y, cx, cy, rot }) {
    const sess = sessions.get(session_id);
    if (!sess) throw new Error(`Session not found: ${session_id}`);
    const result = sess.renderer.updateShapeTransform(slide_idx, shape_idx, x, y, cx, cy, rot);
    if (result.startsWith("ERROR:")) throw new Error(result);
    return { ok: true };
  },

  async export_pptx({ session_id }) {
    const sess = sessions.get(session_id);
    if (!sess) throw new Error(`Session not found: ${session_id}`);
    const buffer = await sess.renderer.exportPptx();
    return { base64: Buffer.from(buffer).toString("base64") };
  },

  async unload({ session_id }) {
    sessions.delete(session_id);
    return { ok: true };
  },
};

// --- Main loop ---

const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on("line", async (line) => {
  let id = null;
  try {
    const req = JSON.parse(line);
    id = req.id;
    const handler = handlers[req.method];
    if (!handler) throw new Error(`Unknown method: ${req.method}`);
    const result = await handler(req.params || {});
    process.stdout.write(JSON.stringify({ id, result }) + "\n");
  } catch (err) {
    process.stdout.write(JSON.stringify({ id, error: err.message || String(err) }) + "\n");
  }
});

rl.on("close", () => process.exit(0));

// Signal readiness
process.stdout.write(JSON.stringify({ id: null, result: "ready" }) + "\n");
