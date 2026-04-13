import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import { config, downloadFromApi } from '../config'
import { usePptxRenderer } from '../hooks/usePptxRenderer'
import { usePptxDrag } from '../hooks/usePptxDrag'
import {
  insertSvgInto,
  showOverlay,
  removeOverlay,
  extractShapeInfo,
  reselectShape,
  hexToRgb,
  DEFAULT_SLIDE_CX,
  DEFAULT_SLIDE_CY,
  DEFAULT_SHAPE_SIZE,
  DEFAULT_IMAGE_CX,
  DEFAULT_IMAGE_CY,
  DEFAULT_STROKE_WIDTH,
  DEFAULT_FONT_SIZE,
  type ShapeInfo,
} from '../utils/pptxSvg'
import { ShapeToolbar, TextPanel } from './PptxEditToolbar'
import './PptxSlideViewer.css'

export interface PptxSlideViewerHandle {
  syncIfModified: () => Promise<boolean>
  exportPptx: () => Promise<void>
  readonly modified: boolean
}

interface PptxSlideViewerProps {
  artifactId: string
  filename: string
  downloadUrl: string
  /** Whether the panel is maximized (full editing mode) */
  maximized?: boolean
  /** Called when a shape is selected/deselected — parent can auto-maximize */
  onSelectionChange?: (hasSelection: boolean) => void
  /** Called when modified state changes */
  onModifiedChange?: (modified: boolean) => void
}

export const PptxSlideViewer = forwardRef<PptxSlideViewerHandle, PptxSlideViewerProps>(
  function PptxSlideViewer({ artifactId, filename, downloadUrl, maximized = false, onSelectionChange, onModifiedChange }, ref) {
    const renderer = usePptxRenderer()
    const containerRef = useRef<HTMLDivElement>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selection, setSelection] = useState<ShapeInfo | null>(null)
    const selectedIdx = selection?.idx ?? -1

    // Notify parent when selection changes
    const updateSelection = useCallback((info: ShapeInfo | null) => {
      setSelection(info)
      onSelectionChange?.(info !== null)
    }, [onSelectionChange])

    // Expose handle to parent
    useImperativeHandle(ref, () => ({
      async syncIfModified() {
        if (!renderer.modified) return false
        try {
          const blob = await renderer.exportPptx()
          const resp = await fetch(`${config.api.baseUrl}/artifacts/${artifactId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: blob,
          })
          if (resp.ok) renderer.markSynced()
          return resp.ok
        } catch (e) {
          console.error('Failed to sync edited PPTX:', e)
          return false
        }
      },
      async exportPptx() {
        const blob = await renderer.exportPptx()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = filename.replace(/\.pptx$/i, '') + '_edited.pptx'
        a.click()
        URL.revokeObjectURL(a.href)
      },
      get modified() {
        return renderer.modified
      },
    }), [renderer, artifactId, filename])

    // Notify parent when modified state changes
    useEffect(() => {
      onModifiedChange?.(renderer.modified)
    }, [renderer.modified, onModifiedChange])

    // Load PPTX from API
    useEffect(() => {
      if (!renderer.ready) return
      let cancelled = false

      async function load() {
        try {
          setLoading(true)
          setError(null)
          updateSelection(null)

          const resp = await fetch(`${config.api.baseUrl}${downloadUrl}`)
          if (!resp.ok) throw new Error(`Failed to fetch PPTX: ${resp.status}`)
          const buffer = await resp.arrayBuffer()

          if (cancelled) return
          await renderer.loadPptx(buffer)
          if (cancelled) return

          const svgStr = renderer.renderSlide(0)
          if (containerRef.current) insertSvgInto(containerRef.current, svgStr)
        } catch (e) {
          if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load')
        } finally {
          if (!cancelled) setLoading(false)
        }
      }

      load()
      return () => {
        cancelled = true
      }
    }, [artifactId, downloadUrl, renderer.ready])

    // Render current slide & re-select shape after edits
    const renderAndRefresh = useCallback(
      (shapeIdx?: number) => {
        const svgStr = renderer.renderSlide(renderer.slide)
        if (containerRef.current) insertSvgInto(containerRef.current, svgStr)
        if (shapeIdx !== undefined && shapeIdx >= 0) {
          updateSelection(reselectShape(containerRef.current, shapeIdx))
        }
      },
      [renderer, updateSelection],
    )

    const callAndRefresh = useCallback(
      (fn: () => string, shapeIdx?: number) => {
        const result = fn()
        if (result.startsWith('ERROR:')) { renderer.setStatus(result); return result }
        renderAndRefresh(shapeIdx)
        return result
      },
      [renderer, renderAndRefresh],
    )

    // Click-to-select (maximized/editing mode only)
    useEffect(() => {
      const container = containerRef.current
      if (!container || loading || !maximized) return

      const handleClick = (e: MouseEvent) => {
        const target = e.target as Element
        if (target.classList.contains('resize-handle')) return

        const shapeG = target.closest('g[data-ooxml-shape-idx]') as SVGGElement | null
        if (shapeG) {
          showOverlay(container, shapeG)
          updateSelection(extractShapeInfo(shapeG))
        } else {
          removeOverlay(container)
          updateSelection(null)
        }
      }

      container.addEventListener('click', handleClick)
      return () => container.removeEventListener('click', handleClick)
    }, [loading, maximized, updateSelection])

    // Clear selection when leaving maximized mode
    useEffect(() => {
      if (!maximized && selection) {
        updateSelection(null)
        if (containerRef.current) removeOverlay(containerRef.current)
      }
    }, [maximized])

    // Recalculate overlay position after layout shift
    useLayoutEffect(() => {
      const container = containerRef.current
      if (!selection || !container) return
      const svgEl = container.querySelector('svg')
      if (!svgEl) return
      const g = svgEl.querySelector<SVGGElement>(`g[data-ooxml-shape-idx="${selection.idx}"]`)
      if (!g) return
      showOverlay(container, g)
    }, [selection])

    // Drag/resize
    usePptxDrag({
      containerRef,
      selectedShapeIdx: selectedIdx,
      slide: renderer.slide,
      loading,
      onTransformUpdate: (shapeIdx, x, y, cx, cy, rot) =>
        renderer.updateTransform(renderer.slide, shapeIdx, x, y, cx, cy, rot),
      onDragEnd: useCallback(
        (shapeIdx: number, result: string) => {
          if (!result.startsWith('ERROR')) renderAndRefresh(shapeIdx)
        },
        [renderAndRefresh],
      ),
    })

    // ── Navigation ──
    const goToSlide = useCallback(
      (idx: number) => {
        renderer.setSlide(idx)
        updateSelection(null)
        const svgStr = renderer.renderSlide(idx)
        if (containerRef.current) insertSvgInto(containerRef.current, svgStr)
      },
      [renderer, updateSelection],
    )

    // ── Shape editing handlers ──
    const handleApplyFill = useCallback(
      (hex: string) => {
        if (selectedIdx < 0) return
        const [r, g, b] = hexToRgb(hex)
        callAndRefresh(() => renderer.updateFill(renderer.slide, selectedIdx, r, g, b), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleRemoveFill = useCallback(() => {
      if (selectedIdx < 0) return
      callAndRefresh(() => renderer.updateFill(renderer.slide, selectedIdx, -1, -1, -1), selectedIdx)
    }, [selectedIdx, renderer, callAndRefresh])

    const handleApplyStroke = useCallback(
      (hex: string, dash: string) => {
        if (selectedIdx < 0) return
        const [r, g, b] = hexToRgb(hex)
        callAndRefresh(() => renderer.updateStroke(renderer.slide, selectedIdx, r, g, b, DEFAULT_STROKE_WIDTH, dash), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleRemoveStroke = useCallback(() => {
      if (selectedIdx < 0) return
      callAndRefresh(() => renderer.updateStroke(renderer.slide, selectedIdx, -1, -1, -1, 0), selectedIdx)
    }, [selectedIdx, renderer, callAndRefresh])

    const handleDuplicate = useCallback(() => {
      if (selectedIdx < 0) return
      const result = renderer.duplicateShape(renderer.slide, selectedIdx)
      if (result.startsWith('ERROR:')) { renderer.setStatus(result); return }
      const newIdx = parseInt(result.split(':')[1])
      renderAndRefresh(newIdx)
    }, [selectedIdx, renderer, renderAndRefresh])

    const handleDelete = useCallback(() => {
      if (selectedIdx < 0) return
      const isPic = selection?.shapeType === 'picture'
      const result = isPic
        ? renderer.deleteImage(renderer.slide, selectedIdx)
        : renderer.deleteShape(renderer.slide, selectedIdx)
      if (result.startsWith('ERROR:')) { renderer.setStatus(result); return }
      updateSelection(null)
      renderAndRefresh()
    }, [selectedIdx, selection, renderer, renderAndRefresh, updateSelection])

    // ── Text editing handlers ──
    const handleUpdateText = useCallback(
      (pi: number, ri: number, text: string) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.updateText(renderer.slide, selectedIdx, pi, ri, text), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleUpdateStyle = useCallback(
      (pi: number, ri: number, bold: number, italic: number) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.updateTextRunStyle(renderer.slide, selectedIdx, pi, ri, bold, italic), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleUpdateFontSize = useCallback(
      (pi: number, ri: number, size: number) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.updateTextRunFontSize(renderer.slide, selectedIdx, pi, ri, size), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleUpdateColor = useCallback(
      (pi: number, ri: number, hex: string) => {
        if (selectedIdx < 0) return
        const [r, g, b] = hexToRgb(hex)
        callAndRefresh(() => renderer.updateTextRunColor(renderer.slide, selectedIdx, pi, ri, r, g, b), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleUpdateFont = useCallback(
      (pi: number, ri: number, font: string) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.updateTextRunFont(renderer.slide, selectedIdx, pi, ri, font), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleUpdateDecoration = useCallback(
      (pi: number, ri: number, underline: string, strike: string, baseline: number) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.updateTextRunDecoration(renderer.slide, selectedIdx, pi, ri, underline, strike, baseline), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleUpdateAlign = useCallback(
      (pi: number, align: string) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.updateParagraphAlign(renderer.slide, selectedIdx, pi, align), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleAddParagraph = useCallback(
      (text: string, align: string) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.addParagraph(renderer.slide, selectedIdx, text, align), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleDeleteParagraph = useCallback(
      (pi: number) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.deleteParagraph(renderer.slide, selectedIdx, pi), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleAddRun = useCallback(
      (pi: number, text: string) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.addRun(renderer.slide, selectedIdx, pi, text), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleDeleteRun = useCallback(
      (pi: number, ri: number) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.deleteRun(renderer.slide, selectedIdx, pi, ri), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    const handleAddShapeText = useCallback(
      (text: string) => {
        if (selectedIdx < 0) return
        callAndRefresh(() => renderer.addShapeText(renderer.slide, selectedIdx, text, DEFAULT_FONT_SIZE), selectedIdx)
      },
      [selectedIdx, renderer, callAndRefresh],
    )

    // ── Add shape ──
    const [addShapeType, setAddShapeType] = useState('rect')
    const [addShapeFill, setAddShapeFill] = useState('#4a90d9')

    const handleAddShape = useCallback(() => {
      const [r, g, b] = hexToRgb(addShapeFill)
      const isLine = addShapeType === 'line'
      const cx = DEFAULT_SHAPE_SIZE, cy = isLine ? 0 : DEFAULT_SHAPE_SIZE
      const x = Math.round((DEFAULT_SLIDE_CX - cx) / 2)
      const y = Math.round((DEFAULT_SLIDE_CY - cy) / 2)
      const result = renderer.addShape(renderer.slide, addShapeType, x, y, cx, cy,
        isLine ? -1 : r, isLine ? -1 : g, isLine ? -1 : b)
      if (result.startsWith('ERROR:')) { renderer.setStatus(result); return }
      const newIdx = parseInt(result.split(':')[1])
      if (isLine) renderer.updateStroke(renderer.slide, newIdx, r, g, b, DEFAULT_STROKE_WIDTH)
      renderAndRefresh(newIdx)
    }, [addShapeType, addShapeFill, renderer, renderAndRefresh])

    // ── Image operations ──
    const imageInputRef = useRef<HTMLInputElement>(null)
    const replaceInputRef = useRef<HTMLInputElement>(null)

    const handleAddImage = useCallback(async (file: File) => {
      try {
        const data = new Uint8Array(await file.arrayBuffer())
        const mime = file.type || 'image/png'
        const cx = DEFAULT_IMAGE_CX, cy = DEFAULT_IMAGE_CY
        const x = Math.round((DEFAULT_SLIDE_CX - cx) / 2), y = Math.round((DEFAULT_SLIDE_CY - cy) / 2)
        const result = await renderer.addImage(renderer.slide, data, mime, x, y, cx, cy)
        if (result.startsWith('ERROR:')) { renderer.setStatus(result); return }
        const newIdx = parseInt(result.split(':')[1])
        renderAndRefresh(newIdx)
      } catch (err) { renderer.setStatus(`Error: ${(err as Error).message}`) }
    }, [renderer, renderAndRefresh])

    const handleReplaceImage = useCallback(async (file: File) => {
      if (selectedIdx < 0) return
      try {
        const data = new Uint8Array(await file.arrayBuffer())
        const result = await renderer.replaceImage(renderer.slide, selectedIdx, data, file.type || 'image/png')
        if (result.startsWith('ERROR:')) { renderer.setStatus(result); return }
        renderAndRefresh(selectedIdx)
      } catch (err) { renderer.setStatus(`Error: ${(err as Error).message}`) }
    }, [selectedIdx, renderer, renderAndRefresh])

    // ── Slide management ──
    const handleAddSlide = useCallback(async () => {
      try {
        const { insertedIdx } = await renderer.addSlide(renderer.slide)
        goToSlide(insertedIdx)
      } catch (err) { renderer.setStatus(`Error: ${(err as Error).message}`) }
    }, [renderer, goToSlide])

    const handleDuplicateSlide = useCallback(async () => {
      try {
        const { insertedIdx } = await renderer.addSlide(renderer.slide, renderer.slide)
        goToSlide(insertedIdx)
      } catch (err) { renderer.setStatus(`Error: ${(err as Error).message}`) }
    }, [renderer, goToSlide])

    const handleDeleteSlide = useCallback(async () => {
      if (renderer.total <= 1) return
      const idx = renderer.slide
      try {
        await renderer.deleteSlide(idx)
        goToSlide(Math.min(idx, renderer.total - 2))
      } catch (err) { renderer.setStatus(`Error: ${(err as Error).message}`) }
    }, [renderer, goToSlide])

    const handleMoveSlide = useCallback(async (dir: -1 | 1) => {
      const cur = renderer.slide
      if (cur + dir < 0 || cur + dir >= renderer.total) return
      const order = Array.from({ length: renderer.total }, (_, i) => i)
      ;[order[cur], order[cur + dir]] = [order[cur + dir], order[cur]]
      try {
        await renderer.reorderSlides(order)
        const newIdx = cur + dir
        renderer.setSlide(newIdx)
        goToSlide(newIdx)
      } catch (err) { renderer.setStatus(`Error: ${(err as Error).message}`) }
    }, [renderer, goToSlide])

    const isPicture = selection?.shapeType === 'picture'

    return (
      <div className="pptx-viewer">
        {/* Main body: left-right split when editing */}
        <div className="pptx-viewer__body">
          {/* Left: slide view */}
          <div className="pptx-viewer__left">
            {/* SVG container */}
            <div className="pptx-viewer__slide-container">
              {loading && (
                <div className="pptx-viewer__overlay">
                  <div className="pptx-viewer__spinner" />
                  <span>プレゼンテーションを読み込み中...</span>
                </div>
              )}
              {error && (
                <div className="pptx-viewer__overlay">
                  <span>読み込みエラー: {error}</span>
                  <button className="pptx-viewer__action-btn" onClick={() => downloadFromApi(downloadUrl, filename)}>
                    ダウンロード
                  </button>
                </div>
              )}
              <div
                ref={containerRef}
                className="pptx-viewer__slide pptx-viewer__slide--interactive"
                style={{
                  cursor: selectedIdx >= 0 ? 'move' : 'default',
                  visibility: loading || error ? 'hidden' : 'visible',
                }}
              />
            </div>

            {/* Controls bar */}
            {!loading && !error && (
              <div className="pptx-viewer__controls">
                {/* Slide navigation (always visible) */}
                <button
                  className="pptx-viewer__nav-btn"
                  onClick={() => goToSlide(Math.max(0, renderer.slide - 1))}
                  disabled={renderer.slide === 0}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="15 18 9 12 15 6" />
                  </svg>
                </button>
                <span className="pptx-viewer__page-info">
                  {renderer.slide + 1} / {renderer.total}
                </span>
                <button
                  className="pptx-viewer__nav-btn"
                  onClick={() => goToSlide(Math.min(renderer.total - 1, renderer.slide + 1))}
                  disabled={renderer.slide >= renderer.total - 1}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </button>

                {/* Editing controls (maximized only) */}
                {maximized && (
                  <>
                    <span className="pptx-viewer__controls-sep" />

                    {/* Add shape */}
                    <select value={addShapeType} onChange={e => setAddShapeType(e.target.value)}
                      className="pptx-viewer__select" title="図形の種類">
                      <option value="rect">四角形</option>
                      <option value="ellipse">楕円</option>
                      <option value="roundRect">角丸</option>
                      <option value="line">線</option>
                    </select>
                    <input type="color" value={addShapeFill} onChange={e => setAddShapeFill(e.target.value)}
                      className="pptx-viewer__color-input" title="図形の色" />
                    <button className="pptx-viewer__action-btn" onClick={handleAddShape}>+ 図形</button>

                    {/* Add/replace image */}
                    <input ref={imageInputRef} type="file" accept="image/*" style={{ display: 'none' }}
                      onChange={e => { const f = e.target.files?.[0]; if (f) handleAddImage(f); e.target.value = '' }} />
                    <button className="pptx-viewer__action-btn" onClick={() => imageInputRef.current?.click()}>+ 画像</button>
                    {isPicture && (
                      <>
                        <input ref={replaceInputRef} type="file" accept="image/*" style={{ display: 'none' }}
                          onChange={e => { const f = e.target.files?.[0]; if (f) handleReplaceImage(f); e.target.value = '' }} />
                        <button className="pptx-viewer__action-btn" onClick={() => replaceInputRef.current?.click()}>置換</button>
                      </>
                    )}

                    <span className="pptx-viewer__controls-sep" />

                    {/* Slide management */}
                    <button className="pptx-viewer__action-btn" onClick={handleAddSlide}>+ スライド</button>
                    <button className="pptx-viewer__action-btn" onClick={handleDuplicateSlide}>複製</button>
                    <button className="pptx-viewer__action-btn" onClick={() => handleMoveSlide(-1)}
                      disabled={renderer.slide === 0} title="スライドを左へ移動">&larr;</button>
                    <button className="pptx-viewer__action-btn" onClick={() => handleMoveSlide(1)}
                      disabled={renderer.slide >= renderer.total - 1} title="スライドを右へ移動">&rarr;</button>
                    <button className="pptx-viewer__action-btn pptx-viewer__action-btn--danger"
                      onClick={handleDeleteSlide} disabled={renderer.total <= 1}>削除</button>

                  </>
                )}
              </div>
            )}
          </div>

          {/* Right: editing sidebar (only when shape selected) */}
          {selection && (
            <div className="pptx-viewer__sidebar">
              <ShapeToolbar
                shapeLabel={selection.label}
                fillHex={selection.fillHex}
                onApplyFill={handleApplyFill}
                onRemoveFill={handleRemoveFill}
                onApplyStroke={handleApplyStroke}
                onRemoveStroke={handleRemoveStroke}
                onDuplicate={handleDuplicate}
                onDelete={handleDelete}
              />
              <TextPanel
                paragraphs={selection.paragraphs}
                onUpdateText={handleUpdateText}
                onUpdateStyle={handleUpdateStyle}
                onUpdateFontSize={handleUpdateFontSize}
                onUpdateColor={handleUpdateColor}
                onUpdateFont={handleUpdateFont}
                onUpdateDecoration={handleUpdateDecoration}
                onUpdateAlign={handleUpdateAlign}
                onAddParagraph={handleAddParagraph}
                onDeleteParagraph={handleDeleteParagraph}
                onAddRun={handleAddRun}
                onDeleteRun={handleDeleteRun}
                onAddShapeText={handleAddShapeText}
              />
            </div>
          )}
        </div>
      </div>
    )
  },
)
