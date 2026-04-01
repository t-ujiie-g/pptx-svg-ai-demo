/**
 * PptxEditToolbar — fill color picker + text run editors for selected shapes.
 */

import { useState, useEffect } from 'react'
import type { TextRun } from '../utils/pptxSvg'
import './PptxEditToolbar.css'

// ── Fill toolbar ──

interface FillToolbarProps {
  fillColor: string
  shapeLabel: string
  onApplyFill: (hex: string) => void
}

export function FillToolbar({ fillColor, shapeLabel, onApplyFill }: FillToolbarProps) {
  const [color, setColor] = useState(fillColor)

  useEffect(() => {
    setColor(fillColor)
  }, [fillColor])

  return (
    <div className="pptx-edit-fill">
      <label className="pptx-edit-fill__label">塗りつぶし:</label>
      <input
        type="color"
        value={color}
        onChange={(e) => setColor(e.target.value)}
        className="pptx-edit-fill__picker"
      />
      <button className="pptx-edit-fill__apply" onClick={() => onApplyFill(color)}>
        適用
      </button>
      <span className="pptx-edit-fill__divider" />
      <span className="pptx-edit-fill__shape-label">{shapeLabel}</span>
    </div>
  )
}

// ── Text runs panel ──

interface TextRunsPanelProps {
  runs: TextRun[]
  onApplyText: (pi: number, ri: number, text: string) => void
}

export function TextRunsPanel({ runs, onApplyText }: TextRunsPanelProps) {
  if (runs.length === 0) return null

  return (
    <div className="pptx-edit-text">
      <label className="pptx-edit-text__title">テキスト編集:</label>
      <div className="pptx-edit-text__runs">
        {runs.map((run) => (
          <TextRunRow key={`${run.pi}:${run.ri}`} run={run} onApply={onApplyText} />
        ))}
      </div>
    </div>
  )
}

function TextRunRow({
  run,
  onApply,
}: {
  run: TextRun
  onApply: (pi: number, ri: number, text: string) => void
}) {
  const [text, setText] = useState(run.text)

  useEffect(() => {
    setText(run.text)
  }, [run.text])

  return (
    <div className="pptx-edit-text__row">
      <span className="pptx-edit-text__index">P{run.pi}R{run.ri}</span>
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onApply(run.pi, run.ri, text)
        }}
        className="pptx-edit-text__input"
      />
      <button className="pptx-edit-text__apply" onClick={() => onApply(run.pi, run.ri, text)}>
        適用
      </button>
    </div>
  )
}
