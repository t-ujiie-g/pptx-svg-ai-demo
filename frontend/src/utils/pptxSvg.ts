/**
 * SVG DOM utilities for pptx-svg editing.
 * Based on pptx-svg React example (utils/svg.ts).
 */

import { getShapeTransform, emuToPx } from 'pptx-svg'

// ── Types ──

export interface TextRun {
  pi: number
  ri: number
  text: string
}

export interface ShapeInfo {
  idx: number
  label: string
  detail: string
  fillHex: string
  textRuns: TextRun[]
}

// ── Constants ──

const HANDLE_POSITIONS = ['nw', 'n', 'ne', 'w', 'e', 'sw', 's', 'se'] as const
export type HandlePos = (typeof HANDLE_POSITIONS)[number]

/** Default EMU-per-CSS-pixel ratio (96 DPI). Used when SVG is not yet mounted. */
export const EMU_PER_CSS_PX_DEFAULT = 9525
/** Default PPTX slide width in EMU (10 inches, 16:9 widescreen). */
export const DEFAULT_SLIDE_WIDTH_EMU = 9144000
/** Minimum shape size in EMU for drag/resize (prevents zero-size shapes). */
export const MIN_SHAPE_EMU = 50000

// ── SVG insertion ──

export function insertSvgInto(container: HTMLElement, svgString: string) {
  container.querySelector('.selection-overlay')?.remove()

  if (svgString.startsWith('ERROR:')) {
    container.innerHTML = `<span style="color:red;font-family:monospace">${svgString}</span>`
    return
  }

  container.innerHTML = svgString
  const svgEl = container.querySelector('svg')
  if (svgEl) {
    const w = svgEl.getAttribute('width')
    const h = svgEl.getAttribute('height')
    if (w && h && !svgEl.getAttribute('viewBox')) {
      svgEl.setAttribute('viewBox', `0 0 ${w} ${h}`)
    }
    svgEl.removeAttribute('width')
    svgEl.removeAttribute('height')
  }
}

// ── Selection overlay ──

export function removeOverlay(container: HTMLElement) {
  container.querySelector('.selection-overlay')?.remove()
}

export function showOverlay(container: HTMLElement, shapeG: SVGGElement) {
  removeOverlay(container)

  const shapeRect = shapeG.getBoundingClientRect()
  const cr = container.getBoundingClientRect()
  const ox = shapeRect.left - cr.left - container.clientLeft + container.scrollLeft
  const oy = shapeRect.top - cr.top - container.clientTop + container.scrollTop

  const overlay = document.createElement('div')
  overlay.className = 'selection-overlay'
  overlay.style.cssText =
    `position:absolute;pointer-events:none;border:2px solid #4a90d9;z-index:100;` +
    `left:${ox}px;top:${oy}px;width:${shapeRect.width}px;height:${shapeRect.height}px`

  for (const pos of HANDLE_POSITIONS) {
    const h = document.createElement('div')
    h.className = `resize-handle ${pos}`
    h.dataset.handle = pos
    overlay.appendChild(h)
  }

  container.appendChild(overlay)
}

// ── EMU-per-CSS-pixel ──

export function getEmuPerCssPx(svgEl: SVGSVGElement | null): number {
  if (!svgEl) return EMU_PER_CSS_PX_DEFAULT
  const rect = svgEl.getBoundingClientRect()
  const slideCx = parseInt(
    svgEl.getAttribute('data-ooxml-slide-cx') || String(DEFAULT_SLIDE_WIDTH_EMU),
    10,
  )
  return slideCx / rect.width
}

// ── Shape info extraction ──

export function extractShapeInfo(shapeG: SVGGElement): ShapeInfo {
  const idx = parseInt(shapeG.getAttribute('data-ooxml-shape-idx') ?? '-1', 10)
  const fillHex = shapeG.getAttribute('data-ooxml-fill') || ''

  const t = getShapeTransform(shapeG)
  const shapeType = shapeG.getAttribute('data-ooxml-shape-type') || '?'
  const geom = shapeG.getAttribute('data-ooxml-geom') || ''

  return {
    idx,
    label: `Shape #${idx} (${shapeType}${geom ? '/' + geom : ''})`,
    detail: `x=${emuToPx(t.x)}px y=${emuToPx(t.y)}px w=${emuToPx(t.cx)}px h=${emuToPx(t.cy)}px rot=${t.rot}`,
    fillHex: fillHex.length === 6 ? fillHex : '',
    textRuns: extractTextRuns(shapeG),
  }
}

function extractTextRuns(shapeG: SVGGElement): TextRun[] {
  const runTspans = shapeG.querySelectorAll('tspan[data-ooxml-run-idx]')
  if (runTspans.length === 0) return []

  const seen = new Map<string, number>()
  const runs: TextRun[] = []

  for (const ts of runTspans) {
    const ri = ts.getAttribute('data-ooxml-run-idx')
    const paraTspan = ts.closest('tspan[data-ooxml-para-idx]')
    const pi = paraTspan ? paraTspan.getAttribute('data-ooxml-para-idx') : null
    if (pi === null || ri === null) continue

    const key = `${pi}:${ri}`
    if (seen.has(key)) {
      runs[seen.get(key)!].text += ts.textContent || ''
    } else {
      seen.set(key, runs.length)
      runs.push({ pi: parseInt(pi), ri: parseInt(ri), text: ts.textContent || '' })
    }
  }

  return runs
}

// ── Imperative helpers ──

export function reselectShape(container: HTMLElement | null, shapeIdx: number): ShapeInfo | null {
  if (!container) return null
  const svgEl = container.querySelector('svg')
  if (!svgEl) return null
  const g = svgEl.querySelector<SVGGElement>(`g[data-ooxml-shape-idx="${shapeIdx}"]`)
  if (!g) return null
  showOverlay(container, g)
  return extractShapeInfo(g)
}
