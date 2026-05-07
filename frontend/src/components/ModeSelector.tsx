import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Intent,
  INTENT_LABELS,
  ModeSpec,
  StyleSource,
  StyleSourceKind,
  STYLE_SOURCE_KIND_LABELS,
  StylePreset,
  STYLE_PRESET_LABELS,
  inferModeSpec,
  intentRequiresTarget,
  styleSourceRequiresRef,
} from '../types/modeSpec'
import './ModeSelector.css'

const COLLAPSED_STORAGE_KEY = 'mode-selector-collapsed'

function readCollapsedPreference(): boolean {
  try {
    const v = localStorage.getItem(COLLAPSED_STORAGE_KEY)
    if (v === null) return true   // デフォルトは折り畳み
    return v === '1'
  } catch {
    return true
  }
}

function writeCollapsedPreference(collapsed: boolean): void {
  try {
    localStorage.setItem(COLLAPSED_STORAGE_KEY, collapsed ? '1' : '0')
  } catch {
    /* ignore */
  }
}

interface ModeSelectorProps {
  /** 入力テキスト（推定に使う） */
  text: string
  /** 編集対象 PPTX のID（あれば） */
  targetArtifactId?: string
  /** 参照スタイル PPTX のID（あれば） */
  styleRefArtifactId?: string
  /** 参照スタイル PPTX のファイル名（添付したばかりで未アップロードの場合の表示用） */
  styleRefFileName?: string
  /** 現在のModeSpec（外部状態） */
  modeSpec: ModeSpec | null
  onChangeModeSpec: (spec: ModeSpec) => void
  /** 参照スタイル PPTX の選択 */
  onSelectStyleRefFile: (file: File | null) => void
  styleRefFile: File | null
  disabled?: boolean
}

const INTENTS: Intent[] = ['tweak', 'polish', 'restructure', 'from-scratch']
const KINDS: StyleSourceKind[] = ['from-target', 'from-ref', 'preset', 'mix']
const PRESETS: StylePreset[] = ['best-practice', 'bold', 'dense', 'minimal']

export function ModeSelector({
  text,
  targetArtifactId,
  styleRefArtifactId,
  styleRefFileName,
  modeSpec,
  onChangeModeSpec,
  onSelectStyleRefFile,
  styleRefFile,
  disabled,
}: ModeSelectorProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const hasTarget = !!targetArtifactId
  const hasStyleRef = !!styleRefArtifactId || !!styleRefFile

  const [collapsed, setCollapsed] = useState<boolean>(readCollapsedPreference)
  const toggleCollapsed = () => {
    setCollapsed((c) => {
      const next = !c
      writeCollapsedPreference(next)
      return next
    })
  }

  // 自動推定: text/inputs が変わるたびに、user_overridden==false なら更新する。
  // user が一度でも触ったらユーザー入力を尊重し、targetやrefの増減での再推定のみ行う。
  const inferred = useMemo(
    () => inferModeSpec({ text, hasTarget, hasStyleRef }),
    [text, hasTarget, hasStyleRef]
  )

  useEffect(() => {
    // 送信中 (disabled) は推定/補正を停止。送信直後に text='' / styleRefFile=null
    // へ一時的に変わってモードがリセットされるのを防ぐ。
    if (disabled) return

    if (!modeSpec) {
      onChangeModeSpec(inferred)
      return
    }
    if (modeSpec.user_overridden) {
      // user choice を尊重しつつ、矛盾だけは直す（target消失/style_ref消失）
      let needsFix = false
      let next = modeSpec
      if (intentRequiresTarget(modeSpec.intent) && !hasTarget) {
        next = { ...next, intent: 'from-scratch' }
        needsFix = true
      }
      if (styleSourceRequiresRef(modeSpec.style_source.kind) && !hasStyleRef) {
        next = {
          ...next,
          style_source: hasTarget
            ? { kind: 'from-target' }
            : { kind: 'preset', preset: 'best-practice' },
        }
        needsFix = true
      }
      if (needsFix) onChangeModeSpec(next)
      return
    }
    // auto 状態は inferred を反映
    if (
      modeSpec.intent !== inferred.intent ||
      modeSpec.style_source.kind !== inferred.style_source.kind ||
      modeSpec.style_source.preset !== inferred.style_source.preset
    ) {
      onChangeModeSpec(inferred)
    }
  }, [inferred, modeSpec, hasTarget, hasStyleRef, onChangeModeSpec, disabled])

  const current = modeSpec ?? inferred
  const isAuto = !current.user_overridden

  const setIntent = (intent: Intent) => {
    if (intentRequiresTarget(intent) && !hasTarget) return
    onChangeModeSpec({ ...current, intent, user_overridden: true })
  }

  const setStyleKind = (kind: StyleSourceKind) => {
    if (styleSourceRequiresRef(kind) && !hasStyleRef) return
    let next: StyleSource = { kind }
    if (kind === 'preset' || kind === 'mix') {
      next.preset = current.style_source.preset ?? 'best-practice'
    }
    if (kind === 'mix') {
      next.ref_weight = current.style_source.ref_weight ?? 0.7
    }
    onChangeModeSpec({ ...current, style_source: next, user_overridden: true })
  }

  const setPreset = (preset: StylePreset) => {
    onChangeModeSpec({
      ...current,
      style_source: { ...current.style_source, preset },
      user_overridden: true,
    })
  }

  const resetAuto = () => {
    onChangeModeSpec({ ...inferred, user_overridden: false })
  }

  const handleStyleRefSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onSelectStyleRefFile(file)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const showPresetPicker =
    current.style_source.kind === 'preset' || current.style_source.kind === 'mix'

  // 折り畳み時のサマリ
  const summaryParts: string[] = [INTENT_LABELS[current.intent]]
  summaryParts.push(STYLE_SOURCE_KIND_LABELS[current.style_source.kind])
  if (showPresetPicker && current.style_source.preset) {
    summaryParts.push(STYLE_PRESET_LABELS[current.style_source.preset])
  }
  if (hasStyleRef) summaryParts.push('参照ref')
  const summaryText = summaryParts.join(' / ')

  return (
    <div
      className={`mode-selector ${isAuto ? 'mode-selector--auto' : ''} ${
        collapsed ? 'mode-selector--collapsed' : ''
      }`}
    >
      <button
        type="button"
        className="mode-selector__toggle"
        onClick={toggleCollapsed}
        aria-expanded={!collapsed}
        title={collapsed ? 'モード設定を展開' : 'モード設定を折り畳む'}
      >
        <svg
          className="mode-selector__toggle-icon"
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points={collapsed ? '9 18 15 12 9 6' : '6 9 12 15 18 9'} />
        </svg>
        <span className="mode-selector__toggle-label">モード</span>
        <span className="mode-selector__toggle-summary">{summaryText}</span>
        {isAuto && <span className="mode-selector__auto-badge-inline">auto</span>}
      </button>

      {!collapsed && (
      <>
      <div className="mode-selector__row">
        <span className="mode-selector__label">モード</span>
        <div className="mode-selector__chips">
          {INTENTS.map((it) => {
            const requiresTarget = intentRequiresTarget(it)
            const enabled = !requiresTarget || hasTarget
            return (
              <button
                key={it}
                type="button"
                disabled={disabled || !enabled}
                onClick={() => setIntent(it)}
                className={`mode-chip ${current.intent === it ? 'mode-chip--active' : ''}`}
                title={
                  !enabled
                    ? '編集対象 (target PPTX) が必要です'
                    : INTENT_LABELS[it]
                }
              >
                {INTENT_LABELS[it]}
              </button>
            )
          })}
        </div>
      </div>

      <div className="mode-selector__row">
        <span className="mode-selector__label">スタイル元</span>
        <div className="mode-selector__chips">
          {KINDS.map((k) => {
            const requiresRef = styleSourceRequiresRef(k)
            const enabled = !requiresRef || hasStyleRef
            const fromTargetEnabled = k !== 'from-target' || hasTarget
            const ok = enabled && fromTargetEnabled
            return (
              <button
                key={k}
                type="button"
                disabled={disabled || !ok}
                onClick={() => setStyleKind(k)}
                className={`mode-chip ${
                  current.style_source.kind === k ? 'mode-chip--active' : ''
                }`}
                title={
                  !ok
                    ? requiresRef
                      ? '参照スタイル PPTX が必要です'
                      : '対象 PPTX が必要です'
                    : STYLE_SOURCE_KIND_LABELS[k]
                }
              >
                {STYLE_SOURCE_KIND_LABELS[k]}
              </button>
            )
          })}
        </div>
      </div>

      {showPresetPicker && (
        <div className="mode-selector__row">
          <span className="mode-selector__label">プリセット</span>
          <div className="mode-selector__chips">
            {PRESETS.map((p) => (
              <button
                key={p}
                type="button"
                disabled={disabled}
                onClick={() => setPreset(p)}
                className={`mode-chip mode-chip--preset ${
                  current.style_source.preset === p ? 'mode-chip--active' : ''
                }`}
              >
                {STYLE_PRESET_LABELS[p]}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="mode-selector__row">
        <span className="mode-selector__label">参照スタイルPPTX</span>
        <div className="mode-selector__ref-row">
          <input
            ref={fileInputRef}
            type="file"
            accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
            onChange={handleStyleRefSelect}
            hidden
          />
          {styleRefFile || styleRefArtifactId ? (
            <>
              <span className="mode-selector__ref-name">
                {styleRefFile?.name || styleRefFileName || styleRefArtifactId}
              </span>
              <button
                type="button"
                className="mode-selector__ref-clear"
                onClick={() => onSelectStyleRefFile(null)}
                disabled={disabled}
                aria-label="参照スタイルを外す"
              >
                ×
              </button>
            </>
          ) : (
            <button
              type="button"
              className="mode-selector__ref-pick"
              onClick={() => fileInputRef.current?.click()}
              disabled={disabled}
            >
              + PPTXを選択
            </button>
          )}
        </div>

        <div className="mode-selector__status">
          {isAuto ? (
            <span className="mode-selector__auto-badge" title="自動推定中">
              自動推定
            </span>
          ) : (
            <button
              type="button"
              className="mode-selector__reset"
              onClick={resetAuto}
              disabled={disabled}
            >
              自動推定に戻す
            </button>
          )}
        </div>
      </div>
      </>
      )}
    </div>
  )
}
