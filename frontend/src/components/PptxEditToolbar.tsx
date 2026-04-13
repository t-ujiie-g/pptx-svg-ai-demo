/**
 * PptxEditToolbar — Shape editing controls (fill, stroke, actions)
 * TextPanel — Full text editing with paragraph management and run formatting
 * Based on pptx-svg React example (components/EditToolbar.tsx) v0.5.2.
 */

import { useState, useEffect, useRef } from 'react'
import type { ParagraphInfo, TextRun } from '../utils/pptxSvg'
import './PptxEditToolbar.css'

// ── ShapeToolbar (fill, stroke, duplicate, delete) ──

interface ShapeToolbarProps {
  shapeLabel: string
  fillHex: string
  onApplyFill: (hex: string) => void
  onRemoveFill: () => void
  onApplyStroke: (hex: string, dash: string) => void
  onRemoveStroke: () => void
  onDuplicate: () => void
  onDelete: () => void
}

export function ShapeToolbar({
  shapeLabel, fillHex,
  onApplyFill, onRemoveFill, onApplyStroke, onRemoveStroke,
  onDuplicate, onDelete,
}: ShapeToolbarProps) {
  const [fill, setFill] = useState(fillHex ? '#' + fillHex : '#4a90d9')
  const [strokeColor, setStrokeColor] = useState('#000000')
  const [strokeDash, setStrokeDash] = useState('')

  useEffect(() => { if (fillHex) setFill('#' + fillHex) }, [fillHex])

  return (
    <div className="pptx-edit-toolbar">
      <span className="pptx-edit-toolbar__label">塗り</span>
      <input type="color" value={fill} onChange={e => setFill(e.target.value)}
        className="pptx-edit-toolbar__color" />
      <button className="pptx-edit-toolbar__btn" onClick={() => onApplyFill(fill)}>適用</button>
      <button className="pptx-edit-toolbar__btn" onClick={onRemoveFill}>塗りなし</button>

      <span className="pptx-edit-toolbar__sep" />

      <span className="pptx-edit-toolbar__label">線</span>
      <input type="color" value={strokeColor} onChange={e => setStrokeColor(e.target.value)}
        className="pptx-edit-toolbar__color" />
      <select value={strokeDash} onChange={e => setStrokeDash(e.target.value)}
        className="pptx-edit-toolbar__select">
        <option value="">実線</option>
        <option value="dash">破線</option>
        <option value="dot">点線</option>
        <option value="dashDot">一点鎖線</option>
        <option value="lgDash">長破線</option>
      </select>
      <button className="pptx-edit-toolbar__btn" onClick={() => onApplyStroke(strokeColor, strokeDash)}>適用</button>
      <button className="pptx-edit-toolbar__btn" onClick={onRemoveStroke}>枠線なし</button>

      <span className="pptx-edit-toolbar__sep" />

      <button className="pptx-edit-toolbar__btn" onClick={onDuplicate}>複製</button>
      <button className="pptx-edit-toolbar__btn pptx-edit-toolbar__btn--danger" onClick={onDelete}>削除</button>

      <span className="pptx-edit-toolbar__sep" />
      <span className="pptx-edit-toolbar__shape-label">{shapeLabel}</span>
    </div>
  )
}

// ── TextPanel ──

interface TextPanelProps {
  paragraphs: ParagraphInfo[]
  onUpdateText: (pi: number, ri: number, text: string) => void
  onUpdateStyle: (pi: number, ri: number, bold: number, italic: number) => void
  onUpdateFontSize: (pi: number, ri: number, size: number) => void
  onUpdateColor: (pi: number, ri: number, hex: string) => void
  onUpdateFont: (pi: number, ri: number, font: string) => void
  onUpdateDecoration: (pi: number, ri: number, underline: string, strike: string, baseline: number) => void
  onUpdateAlign: (pi: number, align: string) => void
  onAddParagraph: (text: string, align: string) => void
  onDeleteParagraph: (pi: number) => void
  onAddRun: (pi: number, text: string) => void
  onDeleteRun: (pi: number, ri: number) => void
  onAddShapeText: (text: string) => void
}

export function TextPanel({
  paragraphs,
  onUpdateText, onUpdateStyle, onUpdateFontSize, onUpdateColor,
  onUpdateFont, onUpdateDecoration, onUpdateAlign,
  onAddParagraph, onDeleteParagraph, onAddRun, onDeleteRun,
  onAddShapeText,
}: TextPanelProps) {
  return (
    <div className="pptx-edit-text">
      <span className="pptx-edit-text__title">テキスト</span>

      {paragraphs.length === 0 && (
        <AddShapeTextRow onAdd={onAddShapeText} />
      )}

      {paragraphs.map(para => (
        <ParagraphRow
          key={para.pi}
          para={para}
          onUpdateText={onUpdateText}
          onUpdateStyle={onUpdateStyle}
          onUpdateFontSize={onUpdateFontSize}
          onUpdateColor={onUpdateColor}
          onUpdateFont={onUpdateFont}
          onUpdateDecoration={onUpdateDecoration}
          onUpdateAlign={onUpdateAlign}
          onDeleteParagraph={onDeleteParagraph}
          onAddRun={onAddRun}
          onDeleteRun={onDeleteRun}
        />
      ))}

      {paragraphs.length > 0 && <AddParagraphRow onAdd={onAddParagraph} />}
    </div>
  )
}

// ── AddShapeTextRow (for shapes with no text body) ──

function AddShapeTextRow({ onAdd }: { onAdd: (text: string) => void }) {
  const [text, setText] = useState('')

  const doAdd = () => {
    onAdd(text || 'Text')
    setText('')
  }

  return (
    <div className="pptx-edit-text__add-row">
      <input
        type="text" value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') doAdd() }}
        placeholder="テキストを入力..."
        className="pptx-edit-text__input"
      />
      <button className="pptx-edit-toolbar__btn pptx-edit-toolbar__btn--accent" onClick={doAdd}>
        + テキスト追加
      </button>
    </div>
  )
}

// ── ParagraphRow ──

function ParagraphRow({ para, onUpdateText, onUpdateStyle, onUpdateFontSize, onUpdateColor,
  onUpdateFont, onUpdateDecoration, onUpdateAlign, onDeleteParagraph, onAddRun, onDeleteRun,
}: {
  para: ParagraphInfo
} & Pick<TextPanelProps, 'onUpdateText' | 'onUpdateStyle' | 'onUpdateFontSize' | 'onUpdateColor'
  | 'onUpdateFont' | 'onUpdateDecoration' | 'onUpdateAlign' | 'onDeleteParagraph' | 'onAddRun' | 'onDeleteRun'>) {

  return (
    <div className="pptx-edit-text__para">
      <div className="pptx-edit-text__para-header">
        <span className="pptx-edit-text__para-label">P{para.pi}</span>
        <select
          value={para.align}
          onChange={e => onUpdateAlign(para.pi, e.target.value)}
          className="pptx-edit-toolbar__select"
          title="段落の配置"
        >
          <option value="l">左揃え</option>
          <option value="ctr">中央</option>
          <option value="r">右揃え</option>
          <option value="just">両端揃え</option>
        </select>
        <button
          className="pptx-edit-toolbar__btn pptx-edit-toolbar__btn--small"
          onClick={() => {
            const text = prompt('新しいランのテキスト:', '新規テキスト')
            if (text !== null) onAddRun(para.pi, text)
          }}
        >+ ラン</button>
        <button
          className="pptx-edit-toolbar__btn pptx-edit-toolbar__btn--danger pptx-edit-toolbar__btn--small"
          onClick={() => onDeleteParagraph(para.pi)}
          title="段落を削除"
        >削除</button>
      </div>

      {para.runs.map(run => (
        <RunRow
          key={`${run.pi}:${run.ri}`}
          run={run}
          onUpdateText={onUpdateText}
          onUpdateStyle={onUpdateStyle}
          onUpdateFontSize={onUpdateFontSize}
          onUpdateColor={onUpdateColor}
          onUpdateFont={onUpdateFont}
          onUpdateDecoration={onUpdateDecoration}
          onDeleteRun={onDeleteRun}
        />
      ))}
    </div>
  )
}

// ── RunRow ──

function RunRow({ run, onUpdateText, onUpdateStyle, onUpdateFontSize, onUpdateColor,
  onUpdateFont, onUpdateDecoration, onDeleteRun,
}: {
  run: TextRun
  onUpdateText: (pi: number, ri: number, text: string) => void
  onUpdateStyle: (pi: number, ri: number, bold: number, italic: number) => void
  onUpdateFontSize: (pi: number, ri: number, size: number) => void
  onUpdateColor: (pi: number, ri: number, hex: string) => void
  onUpdateFont: (pi: number, ri: number, font: string) => void
  onUpdateDecoration: (pi: number, ri: number, underline: string, strike: string, baseline: number) => void
  onDeleteRun: (pi: number, ri: number) => void
}) {
  const [text, setText] = useState(run.text)
  const [font, setFont] = useState(run.font)
  const textRef = useRef(run.text)
  const fontRef = useRef(run.font)

  useEffect(() => { setText(run.text); textRef.current = run.text }, [run.text])
  useEffect(() => { setFont(run.font); fontRef.current = run.font }, [run.font])

  const applyText = () => {
    if (text !== textRef.current) onUpdateText(run.pi, run.ri, text)
  }
  const applyFont = () => {
    if (font !== fontRef.current) onUpdateFont(run.pi, run.ri, font)
  }

  return (
    <div className="pptx-edit-text__run">
      <span className="pptx-edit-text__run-label">R{run.ri}</span>

      <input
        type="text" value={text}
        onChange={e => setText(e.target.value)}
        onBlur={applyText}
        onKeyDown={e => { if (e.key === 'Enter') applyText() }}
        className="pptx-edit-text__input pptx-edit-text__input--flex"
      />

      <button
        className={`pptx-edit-text__fmt-btn ${run.bold ? 'pptx-edit-text__fmt-btn--active' : ''}`}
        style={{ fontWeight: 'bold' }}
        onClick={() => onUpdateStyle(run.pi, run.ri, run.bold ? 0 : 1, -1)}
        title="太字"
      >B</button>

      <button
        className={`pptx-edit-text__fmt-btn ${run.italic ? 'pptx-edit-text__fmt-btn--active' : ''}`}
        style={{ fontStyle: 'italic' }}
        onClick={() => onUpdateStyle(run.pi, run.ri, -1, run.italic ? 0 : 1)}
        title="斜体"
      >I</button>

      <button
        className={`pptx-edit-text__fmt-btn ${run.underline ? 'pptx-edit-text__fmt-btn--active' : ''}`}
        style={{ textDecoration: 'underline' }}
        onClick={() => onUpdateDecoration(run.pi, run.ri, run.underline ? 'none' : 'sng', '', -1)}
        title="下線"
      >U</button>

      <button
        className={`pptx-edit-text__fmt-btn ${run.strike ? 'pptx-edit-text__fmt-btn--active' : ''}`}
        style={{ textDecoration: 'line-through' }}
        onClick={() => onUpdateDecoration(run.pi, run.ri, '', run.strike ? 'none' : 'sngStrike', -1)}
        title="取り消し線"
      >S</button>

      <input
        type="number"
        defaultValue={run.fontSize > 0 ? Math.round(run.fontSize / 100) : ''}
        placeholder="pt"
        min={1} max={400}
        className="pptx-edit-text__size-input"
        title="フォントサイズ (pt)"
        onChange={e => {
          const pt = parseInt(e.target.value) || 0
          if (pt > 0) onUpdateFontSize(run.pi, run.ri, pt * 100)
        }}
      />

      <input
        type="color"
        defaultValue={run.color.length === 6 ? '#' + run.color : '#000000'}
        className="pptx-edit-toolbar__color pptx-edit-toolbar__color--small"
        title="文字色"
        onChange={e => onUpdateColor(run.pi, run.ri, e.target.value)}
      />

      <input
        type="text" value={font}
        onChange={e => setFont(e.target.value)}
        onBlur={applyFont}
        onKeyDown={e => { if (e.key === 'Enter') applyFont() }}
        placeholder="フォント"
        className="pptx-edit-text__font-input"
        title="フォント名"
      />

      <button
        className="pptx-edit-toolbar__btn pptx-edit-toolbar__btn--danger pptx-edit-toolbar__btn--icon"
        onClick={() => onDeleteRun(run.pi, run.ri)}
        title="ランを削除"
      >&times;</button>
    </div>
  )
}

// ── AddParagraphRow ──

function AddParagraphRow({ onAdd }: { onAdd: (text: string, align: string) => void }) {
  const [text, setText] = useState('')
  const [align, setAlign] = useState('')

  const doAdd = () => {
    onAdd(text, align)
    setText('')
  }

  return (
    <div className="pptx-edit-text__add-para">
      <input
        type="text" value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') doAdd() }}
        placeholder="新しい段落..."
        className="pptx-edit-text__input pptx-edit-text__input--flex"
      />
      <select value={align} onChange={e => setAlign(e.target.value)}
        className="pptx-edit-toolbar__select" title="配置">
        <option value="">継承</option>
        <option value="l">左揃え</option>
        <option value="ctr">中央</option>
        <option value="r">右揃え</option>
        <option value="just">両端揃え</option>
      </select>
      <button className="pptx-edit-toolbar__btn pptx-edit-toolbar__btn--accent" onClick={doAdd}>
        + 段落
      </button>
    </div>
  )
}
