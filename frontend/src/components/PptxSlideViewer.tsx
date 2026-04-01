import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { config, downloadFromApi } from '../config'
import { usePptxRenderer } from '../hooks/usePptxRenderer'
import { usePptxDrag } from '../hooks/usePptxDrag'
import {
  insertSvgInto,
  showOverlay,
  removeOverlay,
  extractShapeInfo,
  reselectShape,
  type ShapeInfo,
} from '../utils/pptxSvg'
import { FillToolbar, TextRunsPanel } from './PptxEditToolbar'
import './PptxSlideViewer.css'

interface PptxSlideViewerProps {
  artifactId: string
  filename: string
  downloadUrl: string
  showHeader?: boolean
}

export function PptxSlideViewer({
  artifactId,
  filename,
  downloadUrl,
  showHeader = true,
}: PptxSlideViewerProps) {
  const renderer = usePptxRenderer()
  const containerRef = useRef<HTMLDivElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<ShapeInfo | null>(null)
  const selectedIdx = selection?.idx ?? -1

  // Load PPTX from API
  useEffect(() => {
    if (!renderer.ready) return
    let cancelled = false

    async function load() {
      try {
        setLoading(true)
        setError(null)
        setSelection(null)

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
    (shapeIdx: number) => {
      const svgStr = renderer.renderSlide(renderer.slide)
      if (containerRef.current) insertSvgInto(containerRef.current, svgStr)
      if (shapeIdx >= 0) {
        setSelection(reselectShape(containerRef.current, shapeIdx))
      }
    },
    [renderer],
  )

  // Click-to-select — re-register when loading completes so containerRef.current is available
  useEffect(() => {
    const container = containerRef.current
    if (!container || loading) return

    const handleClick = (e: MouseEvent) => {
      const target = e.target as Element
      if (target.classList.contains('resize-handle')) return

      const shapeG = target.closest('g[data-ooxml-shape-idx]') as SVGGElement | null
      if (shapeG) {
        showOverlay(container, shapeG)
        setSelection(extractShapeInfo(shapeG))
      } else {
        removeOverlay(container)
        setSelection(null)
      }
    }

    container.addEventListener('click', handleClick)
    return () => container.removeEventListener('click', handleClick)
  }, [loading])

  // Recalculate overlay position after toolbar render causes layout shift
  useLayoutEffect(() => {
    const container = containerRef.current
    if (!selection || !container) return
    const svgEl = container.querySelector('svg')
    if (!svgEl) return
    const g = svgEl.querySelector<SVGGElement>(`g[data-ooxml-shape-idx="${selection.idx}"]`)
    if (!g) return
    showOverlay(container, g)
  }, [selection])

  // Drag/resize — also depends on loading to ensure container is ready
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

  // Slide navigation
  const goToSlide = useCallback(
    (idx: number) => {
      renderer.setSlide(idx)
      setSelection(null)
      const svgStr = renderer.renderSlide(idx)
      if (containerRef.current) insertSvgInto(containerRef.current, svgStr)
    },
    [renderer],
  )

  // Fill color change
  const handleApplyFill = useCallback(
    (hex: string) => {
      if (selectedIdx < 0) return
      const r = parseInt(hex.slice(1, 3), 16)
      const g = parseInt(hex.slice(3, 5), 16)
      const b = parseInt(hex.slice(5, 7), 16)
      const result = renderer.updateFill(renderer.slide, selectedIdx, r, g, b)
      if (!result.startsWith('ERROR')) renderAndRefresh(selectedIdx)
    },
    [selectedIdx, renderer, renderAndRefresh],
  )

  // Text edit
  const handleApplyText = useCallback(
    (pi: number, ri: number, text: string) => {
      if (selectedIdx < 0) return
      const result = renderer.updateText(renderer.slide, selectedIdx, pi, ri, text)
      if (!result.startsWith('ERROR')) renderAndRefresh(selectedIdx)
    },
    [selectedIdx, renderer, renderAndRefresh],
  )

  // Export edited PPTX
  const handleExport = useCallback(async () => {
    try {
      const blob = await renderer.exportPptx()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = filename.replace(/\.pptx$/i, '') + '_edited.pptx'
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      console.error('Export failed:', e)
    }
  }, [renderer, filename])

  const handleDownload = () => downloadFromApi(downloadUrl, filename)

  return (
    <div className="pptx-viewer">
      {showHeader && (
        <div className="pptx-viewer__header">
          <div className="pptx-viewer__filename">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z" />
              <polyline points="13 2 13 9 20 9" />
            </svg>
            <span>{filename}</span>
          </div>
          <div className="pptx-viewer__header-actions">
            {renderer.modified && (
              <button className="pptx-viewer__export-btn" onClick={handleExport} title="編集済みPPTXをダウンロード">
                エクスポート
              </button>
            )}
            <button className="pptx-viewer__download-btn" onClick={handleDownload} title="元のPPTXをダウンロード">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* Edit toolbar (shown when shape selected) */}
      {selection && (
        <>
          <FillToolbar
            fillColor={selection.fillHex ? '#' + selection.fillHex : '#4a90d9'}
            shapeLabel={selection.label}
            onApplyFill={handleApplyFill}
          />
          <TextRunsPanel runs={selection.textRuns} onApplyText={handleApplyText} />
        </>
      )}

      {/* SVG container — always mounted so containerRef is available for event listeners */}
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
            <button className="pptx-viewer__download-btn" onClick={handleDownload}>
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

      {/* Navigation + export */}
      {!loading && !error && renderer.total > 1 && (
        <div className="pptx-viewer__controls">
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
          {renderer.modified && (
            <button className="pptx-viewer__export-btn pptx-viewer__export-btn--controls" onClick={handleExport}>
              エクスポート
            </button>
          )}
        </div>
      )}
    </div>
  )
}
