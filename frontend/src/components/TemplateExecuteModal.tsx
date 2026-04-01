import { useState, useMemo, useCallback } from 'react'
import { SavedPrompt, TemplateVariable } from '../services/savedPrompts'
import { extractVariableNames, resolveTemplate } from '../services/templateUtils'
import './TemplateExecuteModal.css'

interface TemplateExecuteModalProps {
  template: SavedPrompt
  onExecute: (resolvedContent: string, files?: File[]) => void
  onClose: () => void
}

/** ファイルサイズを人間が読める形式にフォーマット */
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function TemplateExecuteModal({
  template,
  onExecute,
  onClose,
}: TemplateExecuteModalProps) {
  // テキスト変数: テンプレート内容の {{var}} から検出
  const textVariableNames = useMemo(() => extractVariableNames(template.content), [template.content])

  // ファイル変数: variables 配列で type='file' のもの（テンプレート内容とは独立）
  const fileVariables = useMemo(
    () => (template.variables || []).filter((v) => v.type === 'file'),
    [template.variables]
  )

  // テキスト変数の初期値をデフォルト値で埋める
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    for (const name of textVariableNames) {
      const varMeta = template.variables?.find((v) => v.name === name)
      initial[name] = varMeta?.defaultValue ?? ''
    }
    return initial
  })

  // ファイル変数用の File オブジェクト格納
  const [fileValues, setFileValues] = useState<Record<string, File>>({})

  const getTextVariableMeta = useCallback(
    (name: string) => template.variables?.find((v) => v.name === name && v.type !== 'file'),
    [template.variables]
  )

  const preview = useMemo(
    () => resolveTemplate(template.content, values),
    [template.content, values]
  )

  // 全変数が埋まっているか（テキスト + ファイル）
  const allFilled = useMemo(() => {
    const textFilled = textVariableNames.every((name) => values[name]?.trim())
    const filesFilled = fileVariables.every((v) => !!fileValues[v.name])
    return textFilled && filesFilled
  }, [textVariableNames, values, fileVariables, fileValues])

  const handleValueChange = (name: string, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }))
  }

  const handleFileChange = (name: string, file: File | null) => {
    if (file) {
      setFileValues((prev) => ({ ...prev, [name]: file }))
    } else {
      setFileValues((prev) => {
        const next = { ...prev }
        delete next[name]
        return next
      })
    }
  }

  const handleExecute = () => {
    if (!allFilled) return
    const files = Object.values(fileValues)
    onExecute(preview, files.length > 0 ? files : undefined)
  }

  const hasTextVariables = textVariableNames.length > 0
  const hasFileVariables = fileVariables.length > 0

  return (
    <div className="template-execute-overlay" onClick={onClose}>
      <div className="template-execute-modal" onClick={(e) => e.stopPropagation()}>
        <div className="template-execute-header">
          <div>
            <h3>{template.name}</h3>
          </div>
          <button className="template-execute-close" onClick={onClose}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="template-execute-body">
          {/* テキスト変数セクション */}
          {hasTextVariables && (
            <div className="template-execute-variables">
              <label className="template-execute-section-label">テキスト変数を入力</label>
              {textVariableNames.map((name) => {
                const meta = getTextVariableMeta(name)
                return (
                  <div key={name} className="template-execute-variable">
                    <label htmlFor={`var-${name}`}>
                      {meta?.label || name}
                      {meta?.description && (
                        <span className="template-execute-hint">{meta.description}</span>
                      )}
                    </label>
                    <input
                      id={`var-${name}`}
                      type="text"
                      value={values[name] || ''}
                      onChange={(e) => handleValueChange(name, e.target.value)}
                      placeholder={meta?.description || name}
                    />
                  </div>
                )
              })}
            </div>
          )}

          {/* ファイル添付セクション */}
          {hasFileVariables && (
            <div className="template-execute-variables">
              <label className="template-execute-section-label">ファイルを添付</label>
              {fileVariables.map((v: TemplateVariable) => {
                const selectedFile = fileValues[v.name]
                return (
                  <div key={v.name} className="template-execute-variable">
                    <label>
                      {v.label || v.name}
                      <span className="template-execute-type-badge">ファイル</span>
                      {v.description && (
                        <span className="template-execute-hint">{v.description}</span>
                      )}
                    </label>
                    <div className="template-execute-file-input">
                      {selectedFile ? (
                        <div className="template-execute-file-selected">
                          <span className="template-execute-file-name">{selectedFile.name}</span>
                          <span className="template-execute-file-size">{formatFileSize(selectedFile.size)}</span>
                          <button
                            className="template-execute-file-remove"
                            onClick={() => handleFileChange(v.name, null)}
                            type="button"
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M18 6L6 18M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      ) : (
                        <label className="template-execute-file-label" htmlFor={`file-${v.name}`}>
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                            <polyline points="17 8 12 3 7 8" />
                            <line x1="12" y1="3" x2="12" y2="15" />
                          </svg>
                          ファイルを選択
                        </label>
                      )}
                      <input
                        id={`file-${v.name}`}
                        type="file"
                        onChange={(e) => {
                          const file = e.target.files?.[0] || null
                          handleFileChange(v.name, file)
                          e.target.value = ''
                        }}
                        hidden
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <div className="template-execute-preview">
            <label className="template-execute-section-label">プレビュー</label>
            <div className="template-execute-preview-content">{preview}</div>
            {hasFileVariables && Object.keys(fileValues).length > 0 && (
              <div className="template-execute-preview-files">
                {Object.values(fileValues).map((f) => (
                  <span key={f.name} className="template-execute-preview-file-chip">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z" />
                      <polyline points="13 2 13 9 20 9" />
                    </svg>
                    {f.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="template-execute-footer">
          <button className="template-execute-cancel" onClick={onClose}>
            キャンセル
          </button>
          <button
            className="template-execute-send"
            onClick={handleExecute}
            disabled={!allFilled}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
            </svg>
            入力
          </button>
        </div>
      </div>
    </div>
  )
}
