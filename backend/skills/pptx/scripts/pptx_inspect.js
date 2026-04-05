/**
 * pptx_inspect.js — Inspect a PPTX file: structure (JSON) + PNG per slide.
 *
 * Usage (subprocess, one-shot):
 *   cat pptx_base64.txt | node pptx_inspect.js [--width=960] [--height=540]
 *
 * Input: stdin = base64-encoded PPTX bytes
 * Output: stdout = single JSON line:
 *   {
 *     "slide_count": N,
 *     "slide_width_emu": int, "slide_height_emu": int,
 *     "slides": [
 *       {
 *         "slide_idx": int,
 *         "shapes": [ { idx, shape_type, x, y, cx, cy, rot, fill_hex?, text_runs? } ],
 *         "png_base64": "..."
 *       }
 *     ]
 *   }
 *
 * Errors are written to stderr and the process exits non-zero.
 */

// Redirect any stray console output to stderr so stdout stays pure JSON.
// pptx-svg's WASM runtime can emit status lines via console.log.
for (const m of ["log", "info", "warn", "debug"]) {
  console[m] = (...a) => process.stderr.write(`[${m}] ${a.join(" ")}\n`);
}

const { JSDOM } = require("jsdom");
const sharp = require("sharp");
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

// Resolve pptx-svg entry point via require.resolve (NODE_PATH-aware) and convert
// to a file URL so dynamic import() from CJS can load the ESM module.
function resolvePptxSvgUrl() {
  const wasmPath = require.resolve("pptx-svg/wasm");
  const pkgDir = path.dirname(path.dirname(wasmPath)); // .../pptx-svg
  return pathToFileURL(path.join(pkgDir, "dist", "index.js")).href;
}

// --- Args ---
function parseArgs() {
  const out = { width: 960, height: 540, png: true };
  for (const arg of process.argv.slice(2)) {
    if (arg === "--no-png") { out.png = false; continue; }
    const m = arg.match(/^--(width|height)=(\d+)$/);
    if (m) out[m[1]] = parseInt(m[2], 10);
  }
  return out;
}

// --- SVG → shape structure ---
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
    const x = parseInt(g.getAttribute("data-ooxml-x") || "0", 10);
    const y = parseInt(g.getAttribute("data-ooxml-y") || "0", 10);
    const cx = parseInt(g.getAttribute("data-ooxml-cx") || "0", 10);
    const cy = parseInt(g.getAttribute("data-ooxml-cy") || "0", 10);
    const rot = parseInt(g.getAttribute("data-ooxml-rot") || "0", 10);

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

    const shape = {
      idx,
      shape_type: shapeType,
      x, y, cx, cy, rot,
    };
    if (geom) shape.geom = geom;
    if (fillHex && fillHex.length === 6) shape.fill_hex = fillHex;
    if (textRuns.length > 0) shape.text_runs = textRuns;
    shapes.push(shape);
  }

  return { shapes, slide_width_emu: slideCx, slide_height_emu: slideCy };
}

// --- SVG → PNG via sharp ---
async function svgToPngBase64(svgString, width, height) {
  const buf = await sharp(Buffer.from(svgString), { density: 150 })
    .resize(width, height, { fit: "inside" })
    .png()
    .toBuffer();
  return buf.toString("base64");
}

// --- Read all stdin into a Buffer ---
function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.on("data", (c) => chunks.push(c));
    process.stdin.on("end", () => resolve(Buffer.concat(chunks)));
    process.stdin.on("error", reject);
  });
}

// --- Main ---
(async () => {
  try {
    const args = parseArgs();

    // Load pptx-svg (ESM) + wasm — resolved via file URL so NODE_PATH works.
    const mod = await import(resolvePptxSvgUrl());
    const { PptxRenderer } = mod;
    const wasmPath = require.resolve("pptx-svg/wasm");
    const wasmBuffer = fs.readFileSync(wasmPath).buffer;

    // Read base64 pptx from stdin, decode
    const stdinBuf = await readStdin();
    const b64 = stdinBuf.toString("utf8").trim();
    const pptxBuf = Buffer.from(b64, "base64");

    const renderer = new PptxRenderer({ logLevel: "error" });
    await renderer.init(wasmBuffer);
    const { slideCount } = await renderer.loadPptx(
      pptxBuf.buffer.slice(pptxBuf.byteOffset, pptxBuf.byteOffset + pptxBuf.byteLength)
    );

    const slides = [];
    let slideW = 0, slideH = 0;
    for (let i = 0; i < slideCount; i++) {
      const svg = renderer.renderSlideSvg(i);
      if (typeof svg === "string" && svg.startsWith("ERROR:")) {
        slides.push({ slide_idx: i, error: svg });
        continue;
      }
      const info = parseSvgShapes(svg);
      if (!slideW) { slideW = info.slide_width_emu; slideH = info.slide_height_emu; }
      const slideOut = { slide_idx: i, shapes: info.shapes };
      if (args.png) slideOut.png_base64 = await svgToPngBase64(svg, args.width, args.height);
      slides.push(slideOut);
    }

    process.stdout.write(JSON.stringify({
      slide_count: slideCount,
      slide_width_emu: slideW,
      slide_height_emu: slideH,
      slides,
    }));
    process.exit(0);
  } catch (err) {
    process.stderr.write(`pptx_inspect error: ${err && err.stack ? err.stack : err}\n`);
    process.exit(1);
  }
})();
