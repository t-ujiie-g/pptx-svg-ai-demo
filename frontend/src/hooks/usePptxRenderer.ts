/**
 * usePptxRenderer — manages PptxRenderer lifecycle for editing.
 * Based on pptx-svg React example (hooks/useRenderer.ts).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { PptxRenderer } from 'pptx-svg'

export function usePptxRenderer() {
  const rendererRef = useRef<PptxRenderer | null>(null)
  const [ready, setReady] = useState(false)
  const [slide, setSlide] = useState(0)
  const [total, setTotal] = useState(0)
  const [modified, setModified] = useState(false)

  // Init Wasm
  useEffect(() => {
    const renderer = new PptxRenderer()
    rendererRef.current = renderer
    renderer.init().then(() => setReady(true)).catch(console.error)
  }, [])

  // Load PPTX from ArrayBuffer
  const loadPptx = useCallback(async (buffer: ArrayBuffer) => {
    const renderer = rendererRef.current
    if (!renderer) return
    const { slideCount } = await renderer.loadPptx(buffer)
    setTotal(slideCount)
    setSlide(0)
    setModified(false)
  }, [])

  const renderSlide = useCallback((idx: number): string => {
    return rendererRef.current?.renderSlideSvg(idx) ?? 'ERROR: renderer not initialized'
  }, [])

  const updateTransform = useCallback(
    (slideIdx: number, shapeIdx: number, x: number, y: number, cx: number, cy: number, rot: number): string => {
      const result = rendererRef.current?.updateShapeTransform(slideIdx, shapeIdx, x, y, cx, cy, rot) ?? 'ERROR'
      if (!result.startsWith('ERROR')) setModified(true)
      return result
    },
    [],
  )

  const updateText = useCallback(
    (slideIdx: number, shapeIdx: number, pi: number, ri: number, text: string): string => {
      const result = rendererRef.current?.updateShapeText(slideIdx, shapeIdx, pi, ri, text) ?? 'ERROR'
      if (!result.startsWith('ERROR')) setModified(true)
      return result
    },
    [],
  )

  const updateFill = useCallback(
    (slideIdx: number, shapeIdx: number, r: number, g: number, b: number): string => {
      const result = rendererRef.current?.updateShapeFill(slideIdx, shapeIdx, r, g, b) ?? 'ERROR'
      if (!result.startsWith('ERROR')) setModified(true)
      return result
    },
    [],
  )

  const exportPptx = useCallback(async (): Promise<Blob> => {
    const renderer = rendererRef.current
    if (!renderer) throw new Error('renderer not initialized')
    const buffer = await renderer.exportPptx()
    return new Blob([buffer], {
      type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    })
  }, [])

  return {
    ready,
    slide,
    setSlide,
    total,
    modified,
    loadPptx,
    renderSlide,
    updateTransform,
    updateText,
    updateFill,
    exportPptx,
  }
}
