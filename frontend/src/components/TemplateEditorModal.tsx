import { useState, useCallback } from 'react'
import { TemplateVariable, savedPromptsService } from '../services/savedPrompts'
import { syncVariables } from '../services/templateUtils'
import './TemplateEditorModal.css'

interface TemplateEditorData {
  name: string
  content: string
  variables: TemplateVariable[]
  summary: string
}

interface TemplateEditorModalProps {
  initialData: TemplateEditorData
  /** 既存テンプレート編集の場合、そのID */
  editId?: string
  sessionId?: string
  onSave: () => void
  onClose: () => void
}

export function TemplateEditorModal({
  initialData,
  editId,
  sessionId,
  onSave,
  onClose,
}: TemplateEditorModalProps) {
  const [name, setName] = useState(initialData.name)
  const [content, setContent] = useState(initialData.content)
  const [variables, setVariables] = useState<TemplateVariable[]>(initialData.variables)
  const [saving, setSaving] = useState(false)

  const textVariables = variables.filter((v) => v.type !== 'file')
  const fileVariables = variables.filter((v) => v.type === 'file')

  const handleContentChange = useCallback(
    (newContent: string) => {
      setContent(newContent)
      setVariables((prev) => syncVariables(newContent, prev))
    },
    []
  )

  const updateVariable = useCallback(
    (index: number, field: keyof TemplateVariable, value: string) => {
      setVariables((prev) => {
        const updated = [...prev]
        updated[index] = { ...updated[index], [field]: value }
        return updated
      })
    },
    []
  )

  const addFileVariable = useCallback(() => {
    const baseName = 'file'
    let counter = fileVariables.length + 1
    let candidateName = `${baseName}_${counter}`
    const usedNames = new Set(variables.map((v) => v.name))
    while (usedNames.has(candidateName)) {
      counter++
      candidateName = `${baseName}_${counter}`
    }
    setVariables((prev) => [
      ...prev,
      {
        name: candidateName,
        label: '添付ファイル',
        description: '',
        defaultValue: '',
        type: 'file' as const,
      },
    ])
  }, [variables, fileVariables.length])

  const removeFileVariable = useCallback((name: string) => {
    setVariables((prev) => prev.filter((v) => v.name !== name))
  }, [])

  const handleSave = async () => {
    if (!name.trim() || !content.trim()) return
    setSaving(true)
    try {
      if (editId) {
        await savedPromptsService.update(editId, {
          name: name.trim(),
          content,
          variables,
          isTemplate: true,
        })
      } else {
        await savedPromptsService.createTemplate(name.trim(), content, variables, sessionId)
      }
      onSave()
    } finally {
      setSaving(false)
    }
  }

  /** 変数の全体インデックスを取得 */
  const getGlobalIndex = (v: TemplateVariable) => variables.indexOf(v)

  return (
    <div className="template-editor-overlay" onClick={onClose}>
      <div className="template-editor-modal" onClick={(e) => e.stopPropagation()}>
        <div className="template-editor-header">
          <h3>テンプレートを編集</h3>
          <button className="template-editor-close" onClick={onClose}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="template-editor-body">
          <div className="template-editor-field">
            <label>テンプレート名</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="テンプレート名を入力..."
              autoFocus
            />
          </div>

          {initialData.summary && (
            <div className="template-editor-summary">
              <span className="template-editor-summary-label">概要:</span>
              {initialData.summary}
            </div>
          )}

          <div className="template-editor-field">
            <label>テンプレート内容</label>
            <div className="template-editor-content-wrapper">
              <textarea
                value={content}
                onChange={(e) => handleContentChange(e.target.value)}
                placeholder={'プロンプトテンプレートを入力...\n{{variable_name}} でテキスト変数を挿入'}
              />
            </div>
          </div>

          {/* テキスト変数セクション */}
          {textVariables.length > 0 && (
            <div className="template-editor-variables">
              <label>
                テキスト変数
                <span className="template-editor-variables-hint">テンプレート内の {'{{変数}}'} から自動検出</span>
              </label>
              {textVariables.map((v) => {
                const idx = getGlobalIndex(v)
                return (
                  <div key={v.name} className="template-variable-row">
                    <div className="template-variable-name">
                      <code>{`{{${v.name}}}`}</code>
                    </div>
                    <div className="template-variable-fields">
                      <div className="template-variable-field-group">
                        <span className="template-variable-field-label">表示名</span>
                        <input
                          type="text"
                          value={v.label}
                          onChange={(e) => updateVariable(idx, 'label', e.target.value)}
                          placeholder="例: プロジェクト名"
                        />
                      </div>
                      <div className="template-variable-field-group">
                        <span className="template-variable-field-label">説明</span>
                        <input
                          type="text"
                          value={v.description}
                          onChange={(e) => updateVariable(idx, 'description', e.target.value)}
                          placeholder="例: 対象のプロジェクト名を入力してください"
                        />
                      </div>
                      <div className="template-variable-field-group">
                        <span className="template-variable-field-label">デフォルト値</span>
                        <input
                          type="text"
                          value={v.defaultValue}
                          onChange={(e) => updateVariable(idx, 'defaultValue', e.target.value)}
                          placeholder="例: ProjectX"
                        />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* ファイル添付セクション */}
          <div className="template-editor-files">
            <label>
              ファイル添付
              <span className="template-editor-variables-hint">実行時にファイルを添付する設定</span>
            </label>
            {fileVariables.map((v) => {
              const idx = getGlobalIndex(v)
              return (
                <div key={v.name} className="template-file-row">
                  <div className="template-file-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z" />
                      <polyline points="13 2 13 9 20 9" />
                    </svg>
                  </div>
                  <div className="template-file-fields">
                    <div className="template-variable-field-group">
                      <span className="template-variable-field-label">表示名</span>
                      <input
                        type="text"
                        value={v.label}
                        onChange={(e) => updateVariable(idx, 'label', e.target.value)}
                        placeholder="例: レポートファイル"
                      />
                    </div>
                    <div className="template-variable-field-group">
                      <span className="template-variable-field-label">説明</span>
                      <input
                        type="text"
                        value={v.description}
                        onChange={(e) => updateVariable(idx, 'description', e.target.value)}
                        placeholder="例: 分析対象のCSVファイル"
                      />
                    </div>
                  </div>
                  <button
                    className="template-file-remove"
                    onClick={() => removeFileVariable(v.name)}
                    aria-label="この添付ファイル設定を削除"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              )
            })}
            <button className="template-add-file-btn" onClick={addFileVariable}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 5v14M5 12h14" />
              </svg>
              ファイル添付を追加
            </button>
          </div>
        </div>

        <div className="template-editor-footer">
          <button className="template-editor-cancel" onClick={onClose}>
            キャンセル
          </button>
          <button
            className="template-editor-save"
            onClick={handleSave}
            disabled={!name.trim() || !content.trim() || saving}
          >
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

export type { TemplateEditorData }
